#!/opt/homebrew/bin/python3
"""monitor_data.py - the data engine behind Agents.app, and a CLI that prints the same thing.

Mason's spec, verbatim: "i want to see title of conversation, short description (200 character
max), amount of time spent on task total, # of tasks currently running, # of tasks being run"
... "in a table. thats the entire app". Underneath the table: "a giant scrollable list of tasks
that are waiting on me. Yellow if it requires more than me just reading and making a decision."

READ-ONLY toward everything of Mason's and the lab's. The only files this module writes are its own
cache files in ~/Library/Caches/com.masondean.agents/, each by atomic replace: state-v<engine>.json
(the transcript cache, named by engine version so an older engine still running in his open app
never trades entries with this one), waits.json (first_seen per waiting item, earliest wins) and
storage.json (free-space samples and scratch sizes at first sight). queue.py is loaded and
built under two guards, because queue.build() otherwise rewrites lab-common/.queue-manifest.json,
which is what queue.py's own "vanished since last run" report is measured against; an app
refreshing every few seconds would reset that for the coordinator. (1) Its `open` is replaced by
one that refuses every write. (2) While queue.py is loading or building, on that thread, an audit
hook (sys.addaudithook) refuses every file write anywhere except under
~/Library/Caches/com.masondean.agents/: write-mode opens by any route (open, io.open, pathlib,
os.open, tempfile), rename and replace, remove, mkdir, rmdir, chmod, utime, truncate, links and
symlinks. A refused write raises PermissionError inside queue.py; if queue.py does not catch it,
waiting() reports the failure in its message.

Usage (SPEC section 6: this is how agents "check this list"):
    python3 monitor_data.py              open alarms FIRST, then the table, the storage strip and the
                                         waiting list, as plain text
    python3 monitor_data.py --json       the same as JSON; its first key is "alarms"
    python3 monitor_data.py --selftest   the planted controls; exit status 1 if any fails

For the app:
    conversations()  -> list of rows, sidebar order, each a dict with exactly:
                        title, description, seconds_working, time_text, running_now, tasks_run,
                        session_id, pid, tty, note   (note is "" when every source was read)
    waiting()        -> dict: ok, message, total, counts, sha, items
                        items: each a dict with id, text, lane, bucket, needs, yellow, source
                        When queue.py cannot run: ok False, message says so, total and counts None.
                        Never an empty list standing in for "could not read".

    Added for SPEC sections 1, 2, 5 and 10 (engine version 5):
    conversations(w=None) rows also carry:
        headline, summary   dicts: text (the raw Markdown line, never cut), visible, visible_len,
                            limit (50 or 200), complete, over, ok, code; summary also "from"
        waiting_on_you      the headline's visible text starts "Waiting on you:"
        full_text, full_text_ts, full_text_cut, text_source ("transcript" or "lane status")
        working             True, False, or None when nothing was read; registry_status; last_entry_ts
        ticking             True while the transcript is mid-turn (the Time spent clock ticks only then)
        lane                the roster lane of the session, or None
        decisions_waiting, total_wait_seconds, waits_as_of   from w, or else the last good
                            waiting() result of this process when under 180 s old; None, shown
                            "?", when there is none, the last waiting() failed, or the row has no
                            session id
    waiting(now=None) also returns: enriched, as_of, unowned, unowned_wait_seconds,
        may_be_settled_count, stale_total, and enrich_note only when the extra numbers failed.
        unjustified: queue.py's WAITING ON lines that give no "because" (fence 50), NOT counted in
        total or counts: [{"key", "lane", "field", "text"}], key a stable 10-character id made here
        (queue.py gives these lines none); unjustified_total. SPEC section 11, "asks without a reason".
        Each item also carries: world, world_note, owner_lane, owner_session, first_seen,
        waiting_since, waited_seconds, wait_at_least, since_from, since_precision, record_date,
        may_be_settled, settled_reason, settled_reasons.
    alarms(ledger=None) -> alarm.open_alarms(): list of dicts id, from, why, t, when, acks, stale.
        Raises when alarm.py cannot be loaded.
    storage() -> dict: ok, message, volume, free_gib, floor_gib, level (normal, orange, red),
        after_running_gib, declared_remaining_gib, runs (name, lane, pid, pid_alive, declared_gib,
        used_gib, remaining_gib, reading, hours_left, scratch), no_running_work_declares_disk,
        runs_note, trend_gib_per_hour, trend_text, trend_samples, trend_note, time_machine
        (running, phase, percent, note), as_of, text (the strip, one line).
    Helpers for ticking: live_seconds(row, now), clock_text(seconds), wait_text(seconds).

DEFINITIONS (the checkers test against these)

Conversation. One row per cmux workspace whose terminal runs Claude, in sidebar order:
windows[] in file order, then windows[].tabManager.workspaces[] in file order, never re-sorted.
The workspace's tty is the first panel's ttyName (later panels are tried only if the first has
no Claude). A workspace whose tty has no /opt/homebrew/bin/claude process in `ps` is skipped.
Title: customTitle when customTitleSource is "user"; otherwise processTitle with its leading
status glyph run stripped (Claude Code prefixes its terminal title with a glyph such as the
asterisk-like dingbats, the half-circles, or a braille spinner, then a space); if that is empty,
the first panel's title stripped the same way; then customTitle of any source; then the tty.
If the cmux file cannot be read, or is not in the expected shape (the top level must be an object
and "windows" a list; windows, tab managers, workspaces and panels that are not objects are
skipped), every live Claude process is listed in tty order under its registry name, with a note
saying so. The same fallback runs when the file reads but NO live Claude terminal matches any
workspace (a changed layout, such as a renamed ttyName field), with the note "cmux sidebar file
has no terminal names this app can match, listed by terminal". When some live Claude terminals
match and others do not, the unmatched ones are added after the sidebar rows, in tty order, with
the note "not in the cmux sidebar". A live Claude process is never dropped without a row.
Every row is filled independently: an unexpected failure while reading one conversation becomes
that row's note ("could not be read: ..."), its counts show "?", and the other rows are unaffected.
Notes say only what was observed: "no Claude registry file for pid N" (missing) is kept apart from
"Claude registry file for pid N unreadable (...)"; "no agent text yet" is said only when the
transcript was read; "no lane status file" when the roster maps a lane but its status file does
not exist, "lane status file unreadable" when it exists but cannot be parsed.

Description, 200 characters at most. The agent's MOST RECENT message text: the last assistant
entry in the transcript that has a non-empty text block (its text blocks joined). Synthetic
entries (model "<synthetic>", e.g. "You've hit your session limit") are not the agent's words
and are skipped. Markdown is removed: fenced code blocks dropped whole, headings, bullets and
numbered-list markers (also when wrapped in bold, as in "**1. Done.**"), block quotes, table pipes
and table rule lines, bold, italics, strike, code ticks, links reduced to their text. Every em dash becomes a comma. Headings are labels, not
sentences, and are used only when nothing else remains. Each remaining line is a unit; a line that ends without punctuation and is followed by a line starting in lower case is
joined to it (wrapped prose). Units are split into sentences at . ! or ? followed by a space and
a capital, digit or opening bracket or quote. A colon does not end a sentence: a sentence that ends
in a colon (a lead-in such as "Summary:") is joined to the sentence after it and the two count as
one. The first two sentences are joined, whitespace is
collapsed, and if the result is over 200 characters it is cut on a word boundary and ends in a
single ellipsis character, 200 characters in total at most. No agent text yet: the headline of
lab-common/status/<file>.json when lab-common/roster.json maps the sessionId to a lane (its
status_file, else <lane>.json), put through the same cleaning.

Time spent (seconds_working, time_text). Total WORKING time over the whole transcript. The series
is every user and assistant entry that has a timestamp and is not a sidechain, in file order.
Each gap between consecutive series entries is added, capped at 30 minutes (a sleeping laptop),
EXCEPT a gap that ends at a prompt from outside: a user entry that is not a tool_result (a human
message, a <task-notification>, a <cross-session-message>, a meta entry, anything whose content
is not a tool_result). That gap was waiting and adds nothing. Negative gaps add nothing.
Queue operations, attachments and system entries are NOT in the series. Evidence, measured
10 Sep 2026 over all 894 MB of transcripts on this Mac: every "queued_command" attachment lands
within 60 s of a tool_use (it is mid-work delivery, never an idle wake-up), and of the queue
enqueues that followed a quiet minute, 1810 were followed by a real user prompt entry (so the
wait is already excluded) and about 170 by a tool_result or assistant entry (an enqueue during a
long tool call or long generation, which is working time and is counted). Splitting gaps at
enqueue times instead would silently delete working time every time a Monitor event arrives.
A restart boundary normally opens with a prompt, so it reads as waiting; the cap bounds it if not.
Shown as "12 h 40 m" (hours and whole minutes), "45 m", or "under 1 m".

Tasks run (tasks_run). Every task the conversation has started, counted from its tool calls:
Agent (or the older Task) calls, foreground or background; Bash calls with run_in_background
true; Monitor calls; Workflow calls. Also a foreground Bash call that was moved to the background
while running: it became a background task. Its result carries toolUseResult.backgroundTaskId,
and its text starts with one of two wordings, "Command running in background with ID: X" or
"Command did not complete within its 120s timeout and was moved to the background (ID: X)".
The id is taken from backgroundTaskId, else from either wording matched at the START of the
result text only (a command whose output merely quotes the phrase is not a launch). A call whose result is an error and carries no task id (refused by the
permission classifier, invalid script, "user doesn't want to proceed") never started and is
not counted. A call with no result yet is counted. TaskCreate and TaskUpdate are the to-do list,
not tasks, and are not counted.

Running now (running_now). Of those, the ones still going. Finished means ANY of:
  - a foreground call's tool_result arrived (a foreground Agent's result is its finished report);
  - a <task-notification> whose <task-id> or <tool-use-id> names it reports a terminal status
    (completed, failed, killed, stopped, or error/cancelled/timeout); Monitor event
    notifications carry no status and change nothing;
  - a TaskStop result names its id ("Successfully stopped task: X", or "No task found");
  - it was launched before the conversation's current Claude process started, using the
    registry's startedAt (~/.claude/sessions/<pid>.json); a restart kills background tasks.
    If the registry has no usable startedAt, the process start time from ps is used instead,
    and the row's note says so. If the registry file is missing or unreadable, the session id
    is unknown, no transcript is read, and both counts show "?". The registry startedAt can sit
    about a minute after the process really started; a task launched inside that first minute
    would read as finished.
A foreground call with no tool_result yet IS running. A background launch (Bash, Monitor,
Workflow, async Agent) runs until one of the above. An agent resumed by SendMessage ("had no
active task; resumed", "was stopped (completed); resumed", or a resumedAgentId) runs again from
the resume time until its next terminal notification; it is not counted as a new task.
Notifications are read ONLY from user entries' own text (never tool_result content, which can
quote a notification), from queue-operation enqueue content, and from "queued_command"
attachment prompts. Known limitation: if an agent is resumed between the enqueue and the late
delivery of the same earlier completion, it reads finished until its next notification.

Waiting on you (waiting()). Every item of queue.py's manifest "items" list, in its order, full
text, with the manifest's own total, counts and sha passed straight through, never a recount.
YELLOW when the bucket is anything other than "decision" (hands, ear, permission, off-machine,
or any bucket queue.py adds later); those need more than reading and deciding. "needs", in
plain words: decision "decide", ear "listen", hands "your hands", permission "a permission",
off-machine "away from the Mac". Em dashes in item text become commas (there were none on
10 Sep); nothing else in the text changes.

Headline and summary (SPEC sections 1 and 11). Measured by richtext.py on the message's Markdown
after em dashes become commas; nothing is ever cut. HEADLINE: richtext.opening_line (the first
line that shows any text); ok when it is at most 50 visible characters and not code. It needs no
end punctuation (SPEC section 11, 11 Sep: "a news headline has no end punctuation"), so "Waiting
on you: approve the install" is a valid headline; "complete" still reports whether it ends a
statement, but it does not decide "ok" and the CLI never tags a headline "not a finished
sentence". SUMMARY: must be complete (richtext.is_complete: ends in . ! ? or an emoji). When the headline is ok, the
next line that shows text (the second line), else the first line again; when the headline is ok
and there is no second line, the first line, and "from" says so; ok at most 200 visible
characters and complete. "over" is visible_len over the limit; the caller shows the first words
and an "over 50" or "over 200" tag. waiting_on_you: the headline's VISIBLE text, ignoring case,
starts "Waiting on you:" (so **Waiting on you:** counts). Source: the latest message; with no
agent text yet, the lane status headline (text_source says which).

Full text. The latest message whole, up to 100,000 characters; full_text_cut says when it was
longer. full_text_ts is that message's own timestamp, for "written <age> ago".

Working or waiting (SPEC section 1, the ticking column). working is True when the registry status
is "busy", or when the last user or assistant entry did not end a turn. A turn ends at an
assistant entry with no tool call whose stop_reason is end_turn or stop_sequence (or a synthetic
entry), and at his Escape ("[Request interrupted by user..."). Any other prompt (his message, a
peer message, a task notification) starts work; slash-command bookkeeping (<local-command-...>,
<command-...>, <bash-...>) changes nothing. live_seconds() adds the time since the last entry,
capped at 30 minutes like every other gap, only while ticking is True: the transcript itself is
mid-turn. A registry "busy" after a turn ended keeps working True but does not tick, because that
gap ends at a prompt and is never counted, so ticking there was taken back later (11 Sep fix).
clock_text() shows "13 h 34 m 07 s".
His last message (last_human_ts in the transcript state): a prompt whose origin kind is "human".

Decisions waiting per conversation. Each waiting item has an owner lane: stack, when-home and
listens items belong to WORKFLOW (roster lane coordinator); a status file's items belong to the
roster lane whose status_file is that file, else to the lane of the same name. The owner session
is the first roster session of that lane, in roster order, whose Claude process is alive (a
registry file whose pid answers). A row's decisions_waiting counts the items whose owner session
is the row's session, every bucket; total_wait_seconds sums their waited_seconds at waits_as_of.
Items with no live owner are counted in waiting()'s "unowned", so the rows plus unowned add up to
the manifest total.

Waiting time per item (SPEC section 2). first_seen: the first time this engine saw the item id,
kept in waits.json (earliest wins across processes; forgotten after 30 days unseen). Backfill from
a date in the item's OWN record, never from dates its text merely mentions (most are history):
a STACK.md row's state cell "OPEN (6 Sep 19:46)" (the last OPEN outside a "(was ...)" note); a
status record's "when", "asked", "since", "opened", "raised" or "date" field; "since <date>",
"asked <date>", "opened <date>" or "raised <date>" in the first 160 characters of a status line,
else a date inside the line's leading bracket tag, the lane's own label for the item ("[ASKED 8
Sep, never boarded]"), except a tag that names HIS words or question ("[IDEA, his 8 Sep words]",
"[AAX, his presets question, 10 Sep]"): that is when he spoke, not when the question was put to
him, so it is not a start; a rendered status field "Asked: 2026-09-10." (queue.py renders a record's
fields as labelled sentences); a listening folder's creation time. Dates read in local time: "08:4x"
is 08:40 and "7 Sep 19:46" is to the minute, and those are used as the start (wait_at_least False)
when at or before first_seen. A date with only a DAY ("7 Sep", "2026-09-10") cannot say when in that
day, so the start is the earlier of first_seen and the END of that day, and the wait is always "at
least" (a lower bound that is always true; until 11 Sep a bare day read its midnight, which showed
questions written at 19:08 as waiting since 00:00). since_precision ("second", "minute",
"10 minutes", "day") says how much the truth can differ. A day and month take this year, or last
year when this year's is more than a day ahead and last year's is under half a year back; a date
ahead of now is not a start. Otherwise first_seen, and wait_at_least True ("at least").

May be settled (SPEC sections 2 and 11, the free checks). An item is tagged when any of these three
STRONG checks holds; each reason names both sides of its comparison:
  - an ANSWERS-*.md ledger in lab-common (and AGENTS_TEST_LEDGER when set) holds the item id, or
    the first 60 characters of its text (or of its "question" field), compared ignoring case,
    backslashes, asterisks, backticks and runs of white space; at least 20 characters are needed;
  - its world is STALE (a file it names is gone). queue.py keeps STALE items out of its items
    list, so today this fires only if queue.py starts passing them through;
  - its OWN CROSS-LANE row is closed: a row named in the item's leading bracket tag, like
    "[CROSS-LANE row 12]", that sits under the board's CLOSED heading or whose last cell opens
    CLOSED, and is not also listed open. A row cited later in the text is not its row.
The silence check (its owner lane has not re-confirmed it since his last message to that lane:
his last message to any of the lane's sessions is later than the item's record file,
status/<lane>.json or STACK.md, was last written) is DROPPED from "may be settled" (SPEC section
11, 11 Sep: it tagged 16 of 50, mostly because every stack item belongs to WORKFLOW, the window he
writes to most). It is no longer in SETTLE_CHECKS, never tags an item and never counts in
may_be_settled_count; it stays only in HINT_CHECKS, which monitor_actions hands to the headless
checker as context when he presses Return, never as a resolved card.
A check that cannot run says nothing: a false "settled" hides a real item, the worse error.

Alarms (SPEC section 5). alarms() is alarm.open_alarms(): raised and not resolved, oldest first.
The CLI prints them before anything else, and --json puts them first.

Storage (SPEC section 10). free_gib: statvfs of /System/Volumes/Data (f_bavail times f_frsize, in
GiB). after_running_gib: free minus, for each run in runs.json whose state is "running", its
declared disk_gb less what it has used, where used is the growth of its scratch folder since this
engine first saw the run (allocated bytes, symlinks not followed, never negative). A run whose
scratch cannot be read in 1.5 s, or at all, counts its full declaration; a run with no disk_gb
counts nothing and "declares no disk". Scratch folders are measured at most once a minute. Trend:
one free-space sample a minute at most, kept 2 hours; a least-squares line over the last hour,
only with 10 or more samples; "steady" under 0.1 GiB an hour either way. level: red under the
30 GiB floor, orange from 30 to 40, normal above 40. Time Machine: tmutil status (Running, and
BackupPhase and Percent when running), read at most every 30 s. Every figure is an estimate and
the strip says so.

SPEED. Transcripts run to tens of MB. The cache is keyed by transcript path and holds the inode,
a hash of the file's first KB, the byte offset read so far (always the end of the last complete
line), and the running totals (seconds, open tasks by id, counts, last text). Each refresh
reads only NEW bytes. If a file shrinks, its inode changes, or its first KB changes, it is
recomputed from zero. A version stamp in the cache drops it whenever these rules change. An entry
that is not in the expected shape (missing its state or any state field) is recomputed from zero,
and if reading a transcript fails for any reason other than the file being unreadable it is
retried once from zero; if that fails too, the row's note says so.
"""

import calendar
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import stat
import sys
import textwrap
import threading
import time

ENGINE_VERSION = 5

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)                      # lab-common
QUEUE_PY = os.path.join(LAB, "queue.py")
ROSTER = os.path.join(LAB, "roster.json")
STATUS_DIR = os.path.join(LAB, "status")

HOME = os.path.expanduser("~")
CMUX_SESSION = os.path.join(HOME, "Library/Application Support/cmux/session-com.cmuxterm.app.json")
REGISTRY_DIR = os.path.join(HOME, ".claude/sessions")
PROJECTS_DIR = os.path.join(HOME, ".claude/projects")
CACHE_DIR = os.path.join(HOME, "Library/Caches/com.masondean.agents")
# The transcript cache is named by engine version, so two engines running at once (his open app on an
# older version, this CLI on a newer one) can never trade entries with each other.
STATE_PATH = os.path.join(CACHE_DIR, f"state-v{ENGINE_VERSION}.json")
WAITS_PATH = os.path.join(CACHE_DIR, "waits.json")          # first_seen per waiting item; survives engine bumps
STORAGE_PATH = os.path.join(CACHE_DIR, "storage.json")      # free-space samples, scratch sizes at first sight
ALARM_PY = os.path.join(HERE, "alarm.py")
RICHTEXT_PY = os.path.join(HERE, "richtext.py")
CROSS_LANE = os.path.join(LAB, "CROSS-LANE.md")
RUNS = os.path.join(LAB, "runs.json")

GAP_CAP = 30 * 60
DESC_MAX = 200
HEADLINE_MAX = 50
HEADLINE_NEEDS_END = False  # SPEC section 11: a news headline has no end punctuation; only the summary must end
TEXT_CAP = 100_000          # the latest message is kept whole up to this many characters (full_text_cut says when not)
WAITING_PREFIX = "waiting on you:"
COORDINATOR_LANE = "coordinator"
COORDINATOR_ITEM_LANES = ("stack", "when-home", "listens")
GIB = float(1 << 30)
FLOOR_GIB = 30.0
ORANGE_GIB = 40.0
SAMPLE_EVERY = 60           # at most one free-space sample a minute goes into the cache
SAMPLE_KEEP = 2 * 3600
TREND_WINDOW = 3600
TREND_MIN = 10
STEADY_GIB_H = 0.1          # a least-squares slope smaller than this, either way, reads "steady"
SCRATCH_EVERY = 60          # a running run's scratch folder is measured at most once a minute
SCRATCH_BUDGET_S = 1.5      # and a measurement that takes longer is "no scratch reading"
SCRATCH_MAX_ENTRIES = 200_000
TM_EVERY = 30
ELLIPSIS = "\u2026"
EM_DASH = "\u2014"

NEEDS = {
    "decision": "decide",
    "ear": "listen",
    "hands": "your hands",
    "permission": "a permission",
    "off-machine": "away from the Mac",
}

# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------

def no_em_dash(s):
    """Every em dash becomes a comma (standing rule: none anywhere in UI copy or CLI output)."""
    if not s or EM_DASH not in s:
        return s
    s = re.sub(r"\s*" + EM_DASH + r"+\s*", ", ", s)
    return re.sub(r",\s*,", ",", s)


def parse_ts(s):
    """Transcript stamp (UTC ISO, "...Z") to epoch seconds, or None."""
    if not isinstance(s, str) or len(s) < 19:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        try:
            return float(calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
        except ValueError:
            return None


def time_text(seconds):
    s = int(seconds or 0)
    if s < 60:
        return "under 1 m"
    m = s // 60
    if m < 60:
        return f"{m} m"
    return f"{m // 60} h {m % 60} m"


# Leading status glyph run: bullet dot, dingbats and misc symbols (the asterisk-like spinner
# frames), geometric shapes (the half circles), braille (the spinner), then whitespace.
_GLYPH_RUN = re.compile(r"^[\u00b7\u2022\u2217\u25a0-\u25ff\u2600-\u27bf\u2800-\u28ff\u2b00-\u2bff*]+\s+")


def strip_glyph(title):
    if not isinstance(title, str):
        return ""
    return _GLYPH_RUN.sub("", title.strip(), count=1).strip()


def _str(x):
    return x if isinstance(x, str) else ""


def workspace_title(ws, panel=None):
    """The title Mason sees in his cmux sidebar (see DEFINITIONS)."""
    ct = _str(ws.get("customTitle")).strip()
    if ct and ws.get("customTitleSource") == "user":
        return ct
    t = strip_glyph(ws.get("processTitle") or "")
    if t:
        return t
    if panel is None:
        panels = ws.get("panels") or []
        panel = panels[0] if panels else {}
    panel = panel if isinstance(panel, dict) else {}
    t = strip_glyph(panel.get("title") or "")
    if t:
        return t
    if ct:
        return ct
    return _str(panel.get("ttyName")) or "(untitled)"


# ---------------------------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_RULE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_HR = re.compile(r"^([-*_]\s*){3,}$")
_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9\"'(\[])")


def _inline_md(s):
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)          # images
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)           # links
    s = re.sub(r"`+([^`]*)`+", r"\1", s)                     # code ticks
    s = s.replace("`", "")
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)                   # bold
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)   # italics, *x*
    s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", s)     # italics, _x_ (not snake_case)
    s = re.sub(r"~~(.+?)~~", r"\1", s)                       # strike
    s = s.replace("**", "")
    s = s.replace("|", " ")                                  # table pipes
    return s


def clean_markdown_units(text):
    """Markdown removed, one unit per meaningful line (see DEFINITIONS)."""
    units = []
    in_fence = False
    for raw in (text or "").splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        s = raw.strip()
        if not s:
            units.append(None)          # paragraph break
            continue
        if _TABLE_RULE.match(s) or _HR.match(s):
            continue
        structural = False
        while True:
            n = re.sub(r"^>\s?", "", s)
            if n == s:
                break
            s = n.strip()
        heading = False
        if re.match(r"^#{1,6}\s", s):
            s = re.sub(r"^#{1,6}\s+", "", s)
            structural = heading = True
        if re.match(r"^(?:[-*+\u2022]|\d{1,3}[.)])\s+", s):
            s = re.sub(r"^(?:[-*+\u2022]|\d{1,3}[.)])\s+", "", s)
            structural = True
        if s.startswith("|"):
            structural = True
        s = no_em_dash(_inline_md(s)).strip()
        if re.match(r"^(?:[-*+\u2022]|\d{1,3}[.)])\s+", s):         # a marker that was inside bold
            s = re.sub(r"^(?:[-*+\u2022]|\d{1,3}[.)])\s+", "", s)
            structural = True
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            units.append((s, structural, heading))
    # Join wrapped prose: a non-structural line ending without punctuation, followed by a
    # non-structural line starting lower case, is one unit.
    out = []
    for u in units:
        if u is None:
            out.append(None)
            continue
        s, structural, heading = u
        if (out and out[-1] is not None and not structural and not out[-1][1]
                and not re.search(r"[.!?:;]$", out[-1][0]) and s[:1].islower()):
            out[-1] = (out[-1][0] + " " + s, False, False)
        else:
            out.append((s, structural, heading))
    body = [u[0] for u in out if u is not None and not u[2]]
    # Headings are labels, not sentences: used only when the message has nothing else.
    return body or [u[0] for u in out if u is not None]


def describe(text, limit=DESC_MAX):
    sentences = []

    def enough():
        return len(sentences) >= 2 and not sentences[-1].endswith(":")

    for unit in clean_markdown_units(text):
        for part in _SENT_SPLIT.split(unit):
            part = part.strip()
            if not part:
                continue
            if sentences and sentences[-1].endswith(":"):
                sentences[-1] += " " + part           # a colon does not end a sentence
            else:
                sentences.append(part)
            if enough():
                break
        if enough():
            break
    s = re.sub(r"\s+", " ", " ".join(sentences)).strip()
    return cut_words(s, limit)


def cut_words(s, limit=DESC_MAX):
    if len(s) <= limit:
        return s
    head = s[: limit - 1]
    if not s[limit - 1].isspace() and not head[-1:].isspace():
        sp = head.rfind(" ")
        if sp > 0:
            head = head[:sp]
    head = head.rstrip(" ,;:-(\u2013")
    return head + ELLIPSIS


# ---------------------------------------------------------------------------------------------
# Transcript scanner. State is a plain JSON-able dict so it persists as-is.
# ---------------------------------------------------------------------------------------------

AGENT_TOOLS = {"Agent", "Task"}
STOP_TOOLS = {"TaskStop", "KillShell", "KillBash"}
TERMINAL = {"completed", "failed", "killed", "stopped", "error", "errored", "cancelled",
            "canceled", "timeout", "timed_out"}

RE_BG_BASH = re.compile(r"Command running in background with ID: ([\w-]+)")
# Both wordings of a foreground Bash call moved to the background, matched at the START only.
RE_MOVED_BASH = re.compile(r"(?:Command running in background with ID: ([\w-]+)"
                           r"|Command did not complete within its [^\n]{0,40}? timeout and was moved to the "
                           r"background \(ID: ([\w-]+)\))")
RE_MONITOR = re.compile(r"Monitor started \(task ([\w-]+)")
RE_WORKFLOW = re.compile(r"Workflow launched in background\. Task ID: ([\w-]+)")
RE_AGENT_ID = re.compile(r"agentId: ([\w-]+)")
RE_STOPPED = re.compile(r"Successfully stopped task: ([\w-]+)")
RE_NO_TASK = re.compile(r"No task found(?: with ID)?:? ?([\w-]+)?")
RE_RESUMED = re.compile(r"Agent \\?\"([\w-]+)\\?\" (?:had no active task|was stopped[^;]*);\s*resumed")
RE_RESUMED_ID = re.compile(r"\"resumedAgentId\"\s*:\s*\"([\w-]+)\"")
RE_NOTE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
RE_NOTE_ID = re.compile(r"<(?:task-id|tool-use-id)>\s*([^<\s]+)\s*</(?:task-id|tool-use-id)>")
RE_NOTE_STATUS = re.compile(r"<status>\s*([^<]+?)\s*</status>")
END_REASONS = {"end_turn", "stop_sequence"}
# Prompts that start no turn: slash-command bookkeeping and shell-mode echoes. They leave the
# working/waiting state as it was.
NEUTRAL_PROMPTS = ("<local-command-caveat>", "<local-command-stdout>", "<local-command-stderr>",
                   "<command-name>", "<command-message>", "<command-args>", "<bash-input>",
                   "<bash-stdout>", "<bash-stderr>")
INTERRUPTED = "[Request interrupted by user"

_SMALL_MAP_CAP = 300


def new_state():
    return {
        "seconds": 0.0,     # working seconds so far
        "prev_ts": None,    # timestamp of the last series entry
        "confirmed": 0,     # tasks confirmed started (result seen, not an error)
        "pending": {},      # tool_use id -> {"kind", "t"}: a task call with no result yet
        "open": {},         # key -> {"kind", "t", "ids"}: launched in the background, not finished
        "ids": {},          # task id or tool_use id -> open key
        "fg_bash": {},      # foreground Bash tool_use id -> t (watching for "moved to background")
        "stops": {},        # TaskStop tool_use id -> task id from its input
        "sends": {},        # SendMessage tool_use id -> recipient (watching for agent resumes)
        "agents": {},       # every agent id this transcript launched -> launch time
        "last_text": None,
        "last_text_ts": None,
        "last_text_cut": False,  # the latest message was longer than TEXT_CAP
        "end_turn": False,       # the last user or assistant entry ended a turn
        "last_human_ts": None,   # his last message (a prompt with origin kind "human")
        "entries": 0,
        "bad_lines": 0,
    }


def _bounded_put(d, k, v):
    d[k] = v
    if len(d) > _SMALL_MAP_CAP:
        for old in list(d)[: len(d) - _SMALL_MAP_CAP]:
            d.pop(old, None)


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def _finish(st, task_id):
    key = st["ids"].get(task_id)
    if key is not None and key in st["open"]:
        for i in st["open"][key]["ids"]:
            st["ids"].pop(i, None)
        del st["open"][key]
        return
    if task_id in st["pending"]:
        # A completion for a call whose result was not seen yet: it started and it ended.
        st["pending"].pop(task_id)
        st["confirmed"] += 1


def _open(st, key, kind, t, ids):
    st["open"][key] = {"kind": kind, "t": t, "ids": list(ids)}
    for i in ids:
        st["ids"][i] = key


def _notifications(st, text):
    if not isinstance(text, str) or "<task-notification>" not in text:
        return
    for body in RE_NOTE.findall(text):
        header = body.split("<summary>", 1)[0]
        m = RE_NOTE_STATUS.search(header)
        if not m or m.group(1).strip().lower() not in TERMINAL:
            continue                                  # a Monitor event, or not a completion
        for tid in RE_NOTE_ID.findall(header):
            _finish(st, tid)


def _launch_result(st, use_id, p, rc, err, tur, t):
    kind = p["kind"]
    task_id = None
    if kind == "bash":
        m = RE_BG_BASH.search(rc)
        task_id = m.group(1) if m else tur.get("backgroundTaskId")
    elif kind == "monitor":
        m = RE_MONITOR.search(rc)
        task_id = m.group(1) if m else (tur.get("taskId") if not err else None)
    elif kind == "workflow":
        m = RE_WORKFLOW.search(rc)
        task_id = m.group(1) if m else (tur.get("taskId") if not err else None)
    elif kind == "agent":
        is_async = tur.get("status") == "async_launched" or "Async agent launched" in rc
        if is_async:
            m = RE_AGENT_ID.search(rc)
            task_id = m.group(1) if m else tur.get("agentId")
        else:
            if err:
                return                                # refused, never started
            st["confirmed"] += 1                      # a foreground agent's finished report
            if isinstance(tur.get("agentId"), str):
                _bounded_put(st["agents"], tur["agentId"], p["t"])
            return
    if task_id:
        st["confirmed"] += 1
        _open(st, use_id, kind, p["t"], [task_id, use_id])
        if kind == "agent":
            _bounded_put(st["agents"], task_id, p["t"])
    elif not err:
        st["confirmed"] += 1                          # started; result names no id to wait on


def feed(st, e):
    """Advance the state by one transcript entry (already JSON-decoded)."""
    if not isinstance(e, dict) or e.get("isSidechain"):
        return
    st["entries"] += 1
    typ = e.get("type")

    if typ == "queue-operation":
        if e.get("operation") == "enqueue":
            _notifications(st, e.get("content"))
        return
    if typ == "attachment":
        a = e.get("attachment")
        if isinstance(a, dict) and a.get("type") == "queued_command":
            _notifications(st, a.get("prompt"))
        return
    if typ not in ("user", "assistant"):
        return

    msg = e.get("message") if isinstance(e.get("message"), dict) else {}
    content = msg.get("content")
    blocks = content if isinstance(content, list) else []
    t = parse_ts(e.get("timestamp"))

    has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)
    is_prompt = typ == "user" and not has_result

    # Working time: the gap counts unless it ends at a prompt from outside.
    if t is not None:
        prev = st["prev_ts"]
        if prev is not None and not is_prompt:
            gap = t - prev
            if gap > 0:
                st["seconds"] += min(gap, GAP_CAP)
        st["prev_ts"] = t
    tl = t if t is not None else 0.0

    if typ == "assistant":
        has_tool = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks)
        st["end_turn"] = (not has_tool) and (msg.get("stop_reason") in END_REASONS
                                             or msg.get("model") == "<synthetic>")
        texts = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                texts.append(b["text"])
            elif bt == "tool_use":
                name = b.get("name")
                uid = b.get("id")
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                if not uid:
                    continue
                if name in AGENT_TOOLS:
                    st["pending"][uid] = {"kind": "agent", "t": tl}
                elif name == "Monitor":
                    st["pending"][uid] = {"kind": "monitor", "t": tl}
                elif name == "Workflow":
                    st["pending"][uid] = {"kind": "workflow", "t": tl}
                elif name == "Bash":
                    if inp.get("run_in_background") in (True, "true", "True", 1):
                        st["pending"][uid] = {"kind": "bash", "t": tl}
                    else:
                        _bounded_put(st["fg_bash"], uid, tl)
                elif name in STOP_TOOLS:
                    _bounded_put(st["stops"], uid, str(inp.get("task_id") or inp.get("shell_id") or ""))
                elif name == "SendMessage":
                    _bounded_put(st["sends"], uid, str(inp.get("to") or ""))
        if texts and msg.get("model") != "<synthetic>":
            joined = "\n\n".join(texts)
            st["last_text"] = joined[:TEXT_CAP]
            st["last_text_cut"] = len(joined) > TEXT_CAP
            st["last_text_ts"] = t
        return

    # user entry
    if is_prompt:
        ptext = (content if isinstance(content, str) else _result_text(blocks)).lstrip()
        if ptext.startswith(INTERRUPTED):
            st["end_turn"] = True                     # he pressed Escape: the turn is over
        elif not ptext.startswith(NEUTRAL_PROMPTS):
            st["end_turn"] = False
            origin = e.get("origin")
            if isinstance(origin, dict) and origin.get("kind") == "human" and t is not None:
                st["last_human_ts"] = t
    else:
        st["end_turn"] = False
    if isinstance(content, str):
        _notifications(st, content)
        return
    tur_all = e.get("toolUseResult")
    n_results = sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result")
    tur = tur_all if (isinstance(tur_all, dict) and n_results == 1) else {}
    for b in blocks:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            _notifications(st, b.get("text"))
            continue
        if bt != "tool_result":
            continue
        uid = b.get("tool_use_id")
        rc = _result_text(b.get("content"))
        err = bool(b.get("is_error"))
        if uid in st["pending"]:
            p = st["pending"].pop(uid)
            _launch_result(st, uid, p, rc, err, tur, tl)
        elif uid in st["fg_bash"]:
            st["fg_bash"].pop(uid)
            bg = tur.get("backgroundTaskId") if isinstance(tur.get("backgroundTaskId"), str) else None
            if not bg:
                m = RE_MOVED_BASH.match(rc.lstrip())
                bg = (m.group(1) or m.group(2)) if m else None
            if bg:                                    # moved to the background while running
                st["confirmed"] += 1
                _open(st, uid, "bash", tl, [bg, uid])
        elif uid in st["stops"]:
            want = st["stops"].pop(uid)
            m = RE_STOPPED.search(rc)
            if m:
                _finish(st, m.group(1))
            elif not err and isinstance(tur.get("task_id"), str):
                _finish(st, tur["task_id"])
            elif RE_NO_TASK.search(rc) and want:
                _finish(st, want)                     # nothing by that id is running
        elif uid in st["sends"]:
            st["sends"].pop(uid)
            if err:
                continue
            rid = tur.get("resumedAgentId") if isinstance(tur.get("resumedAgentId"), str) else None
            if not rid:
                m = RE_RESUMED_ID.search(rc) or RE_RESUMED.search(rc)
                rid = m.group(1) if m else None
            if rid and rid in st["agents"] and rid not in st["ids"]:
                _open(st, f"resume:{rid}:{tl}", "agent", tl, [rid])


def running_now(st, started_at):
    """Open tasks launched at or after the current process start (restart kills the rest)."""
    n = 0
    for p in list(st["pending"].values()) + list(st["open"].values()):
        if started_at is None or (p.get("t") or 0) >= started_at:
            n += 1
    return n


def tasks_run(st):
    return st["confirmed"] + len(st["pending"])


def feed_line(st, line):
    """One raw JSONL line. Lines that cannot matter are skipped without decoding."""
    if not (b'"type":"user"' in line or b'"type":"assistant"' in line or b"<task-notification>" in line
            or b'"type": "user"' in line or b'"type": "assistant"' in line):
        return
    try:
        e = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        st["bad_lines"] += 1
        return
    feed(st, e)


def _head_hash(path, n):
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read(n)).hexdigest()


_STATE_KEYS = tuple(new_state())


def _entry_ok(entry):
    """A cache entry in the shape this engine writes; anything else is recomputed from zero."""
    if not isinstance(entry, dict) or not isinstance(entry.get("state"), dict):
        return False
    if not isinstance(entry.get("offset", 0), int) or not isinstance(entry.get("head_len", 0), int):
        return False
    stt = entry["state"]
    if any(k not in stt for k in _STATE_KEYS):
        return False
    return all(isinstance(stt[k], dict) for k in ("pending", "open", "ids", "fg_bash", "stops", "sends", "agents"))


def scan_file(path, entry):
    """Bring one transcript's cache entry up to date by reading only new complete lines.
    Returns (entry, changed). Recomputes from zero on shrink, new inode, or a changed head."""
    st = os.stat(path)
    fresh = (
        not _entry_ok(entry)
        or entry.get("engine") != ENGINE_VERSION
        or entry.get("inode") != st.st_ino
        or st.st_size < entry.get("offset", 0)
    )
    if not fresh and entry.get("head_len"):
        try:
            fresh = _head_hash(path, entry["head_len"]) != entry.get("head")
        except OSError:
            fresh = True
    if fresh:
        entry = {"engine": ENGINE_VERSION, "inode": st.st_ino, "offset": 0,
                 "head_len": 0, "head": "", "state": new_state()}
    if st.st_size == entry["offset"]:
        return entry, fresh
    off = entry["offset"]
    state = entry["state"]
    with open(path, "rb") as fh:
        fh.seek(off)
        for line in fh:
            if not line.endswith(b"\n"):
                break                                  # partial last line: read it next time
            off += len(line)
            feed_line(state, line)
    changed = fresh or off != entry["offset"]
    entry["offset"] = off
    if entry["head_len"] < 1024 and off > entry["head_len"]:
        entry["head_len"] = min(1024, off)
        entry["head"] = _head_hash(path, entry["head_len"])
    return entry, changed


# ---------------------------------------------------------------------------------------------
# Cache persistence (shared by the app and the CLI)
# ---------------------------------------------------------------------------------------------

_MEM = {"state": None, "disk_mtime": None}


def _read_disk_state():
    try:
        with open(STATE_PATH) as fh:
            d = json.load(fh)
        if d.get("engine") == ENGINE_VERSION and isinstance(d.get("files"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"engine": ENGINE_VERSION, "files": {}}


def _merge(into, other):
    """Keep, per transcript, whichever entry has read further into the same file."""
    files = other.get("files") if isinstance(other, dict) else None
    for path, ent in (files.items() if isinstance(files, dict) else ()):
        if not isinstance(ent, dict):
            continue
        mine = into["files"].get(path)
        if not isinstance(mine, dict):
            into["files"][path] = ent
            continue
        try:
            if ent.get("inode") == mine.get("inode") and ent.get("offset", 0) > mine.get("offset", 0):
                into["files"][path] = ent
        except TypeError:
            pass


def _cache():
    try:
        mt = os.stat(STATE_PATH).st_mtime
    except OSError:
        mt = None
    if _MEM["state"] is None:
        _MEM["state"] = _read_disk_state()
        _MEM["disk_mtime"] = mt
    elif mt is not None and mt != _MEM["disk_mtime"]:
        _merge(_MEM["state"], _read_disk_state())
        _MEM["disk_mtime"] = mt
    return _MEM["state"]


def _save_cache():
    state = _MEM["state"]
    if state is None:
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        _merge(state, _read_disk_state())
        for path in [p for p in state["files"] if not os.path.exists(p)]:
            del state["files"][path]
        tmp = f"{STATE_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh, separators=(",", ":"))
        os.replace(tmp, STATE_PATH)
        _MEM["disk_mtime"] = os.stat(STATE_PATH).st_mtime
    except OSError:
        pass                                          # a cache that cannot be saved costs time, not truth


# ---------------------------------------------------------------------------------------------
# Live sources
# ---------------------------------------------------------------------------------------------

def claude_processes():
    """tty -> list of (pid, process start epoch) for every claude process on a terminal."""
    out = subprocess.run(["ps", "-axo", "pid=,tty=,lstart=,comm="],
                         capture_output=True, text=True, timeout=10).stdout
    by_tty = {}
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, tty = parts[0], parts[1]
        comm = parts[7].strip()
        if os.path.basename(comm) != "claude" or tty in ("??", "-"):
            continue
        try:
            start = time.mktime(time.strptime(" ".join(parts[2:7]), "%a %b %d %H:%M:%S %Y"))
        except ValueError:
            start = None
        by_tty.setdefault(tty, []).append((int(pid), start))
    for v in by_tty.values():
        v.sort()
    return by_tty


def read_registry(pid):
    with open(os.path.join(REGISTRY_DIR, f"{pid}.json")) as fh:
        d = json.load(fh)
    if not isinstance(d, dict):
        raise ValueError(f"not a JSON object ({type(d).__name__})")
    return d


def cmux_workspaces():
    """[(workspace dict, window index)] in sidebar order."""
    with open(CMUX_SESSION) as fh:
        d = json.load(fh)
    if not isinstance(d, dict):
        raise ValueError(f"top level is not an object ({type(d).__name__})")
    windows = d.get("windows")
    if not isinstance(windows, list):
        raise ValueError(f"windows is not a list ({type(windows).__name__})")
    out = []
    for w in windows:
        tm = w.get("tabManager") if isinstance(w, dict) else None
        wss = tm.get("workspaces") if isinstance(tm, dict) else None
        for ws in (wss if isinstance(wss, list) else []):
            if isinstance(ws, dict):
                out.append(ws)
    return out


_TRANSCRIPT_PATHS = {}


def transcript_path(session_id):
    p = _TRANSCRIPT_PATHS.get(session_id)
    if p and os.path.exists(p):
        return p
    hits = glob.glob(os.path.join(glob.escape(PROJECTS_DIR), "*", f"{session_id}.jsonl"))
    if not hits:
        return None
    p = max(hits, key=lambda h: os.path.getsize(h))
    _TRANSCRIPT_PATHS[session_id] = p
    return p


def roster_headline(session_id):
    """(headline or None, problem or ""). problem is "no lane status file" when the roster maps a
    lane whose status file does not exist, "lane status file unreadable" when it cannot be parsed."""
    with open(ROSTER) as fh:
        r = json.load(fh)
    sessions = r.get("sessions") if isinstance(r, dict) else None
    row = sessions.get(session_id) if isinstance(sessions, dict) else None
    if not isinstance(row, dict):
        return None, ""
    fname = row.get("status_file") or (f'{row["lane"]}.json' if row.get("lane") else None)
    if not isinstance(fname, str) or not fname:
        return None, ""
    try:
        with open(os.path.join(STATUS_DIR, fname)) as fh:
            s = json.load(fh)
    except FileNotFoundError:
        return None, "no lane status file"
    except (OSError, ValueError):
        return None, "lane status file unreadable"
    h = s.get("headline") if isinstance(s, dict) else None
    return (h if isinstance(h, str) and h.strip() else None), ""


# ---------------------------------------------------------------------------------------------
# conversations()
# ---------------------------------------------------------------------------------------------

_ROW_NEW = {"headline": None, "summary": None, "waiting_on_you": False, "full_text": "",
            "full_text_ts": None, "full_text_cut": False, "text_source": "", "working": None,
            "ticking": None, "registry_status": None, "last_entry_ts": None, "lane": None,
            "decisions_waiting": None, "total_wait_seconds": None, "waits_as_of": None}


def _row(title, tty, pid):
    r = {"title": no_em_dash(title), "description": "", "seconds_working": 0, "time_text": "",
         "running_now": None, "tasks_run": None, "session_id": None, "pid": pid, "tty": tty,
         "note": ""}
    r.update(json.loads(json.dumps(_ROW_NEW)))
    return r


def _why(ex):
    return getattr(ex, "strerror", None) or str(ex) or type(ex).__name__


def _scan(path, cache, notes):
    """One transcript brought up to date. A cache entry that makes the scan fail is thrown away and
    the transcript is read again from zero, once; only then does the row get a note."""
    try:
        ent, changed = scan_file(path, cache["files"].get(path))
    except OSError as ex:
        notes.append(f"transcript unreadable ({_why(ex)})")
        return None
    except Exception:
        try:
            ent, changed = scan_file(path, None)
            changed = True
        except OSError as ex:
            notes.append(f"transcript unreadable ({_why(ex)})")
            return None
        except Exception as ex:
            if cache["files"].pop(path, None) is not None:
                cache["_dirty"] = True
            notes.append(f"transcript could not be read ({type(ex).__name__}: {ex})")
            return None
    cache["files"][path] = ent
    if changed:
        cache["_dirty"] = True
    return ent["state"]


def _fill(row, pid, proc_start, notes, cache):
    """Registry, transcript, counts, description. Each source failing adds a note, never raises."""
    try:
        reg = read_registry(pid)
    except FileNotFoundError:
        notes.append(f"no Claude registry file for pid {pid}")
        return                                        # no session id: no transcript, counts "?"
    except (OSError, ValueError) as ex:
        notes.append(f"Claude registry file for pid {pid} unreadable ({_why(ex)})")
        return
    sid = reg.get("sessionId")
    if not isinstance(sid, str) or not sid.strip():
        notes.append("the Claude registry file has no session id")
        return
    row["session_id"] = sid
    rs = reg.get("status")
    row["registry_status"] = rs if isinstance(rs, str) else None
    try:
        row["lane"] = (_roster_sessions().get(sid) or {}).get("lane")
    except (OSError, ValueError):
        pass
    started = reg.get("startedAt")
    if isinstance(started, (int, float)) and not isinstance(started, bool):
        started_at = started / 1000.0
    elif proc_start is not None:
        started_at = proc_start
        notes.append("registry has no start time, used the process start")
    else:
        started_at = None
        notes.append("no process start time, the restart rule was not applied")
    path = transcript_path(sid)
    st = None
    if not path:
        notes.append("transcript not found")
    else:
        st = _scan(path, cache, notes)
    if st is not None:
        row["seconds_working"] = int(st["seconds"])
        row["time_text"] = time_text(st["seconds"])
        row["tasks_run"] = tasks_run(st)
        row["running_now"] = running_now(st, started_at)
        row["last_entry_ts"] = st.get("prev_ts")
        if st.get("last_text"):
            row["description"] = describe(st["last_text"])
            _message_into_row(row, st["last_text"], st.get("last_text_ts"), "transcript",
                              bool(st.get("last_text_cut")), notes)
    row["working"] = working_state(row["registry_status"], st)
    row["ticking"] = ticking_state(st)
    if not row["description"]:
        try:
            h, problem = roster_headline(sid)
        except FileNotFoundError:
            h, problem = None, "no roster file"
        except (OSError, ValueError) as ex:
            h, problem = None, "roster unreadable"
        if h:
            row["description"] = describe(h)
            _message_into_row(row, h, None, "lane status", False, notes)
        else:
            said = (["no agent text yet"] if st is not None else []) + ([problem] if problem else [])
            if said:
                notes.append(", ".join(said))


def working_state(registry_status, st):
    """True while the agent works: its registry status is "busy", or its last user or assistant
    entry did not end a turn. False when neither. None when nothing was read."""
    if registry_status == "busy":
        return True
    if isinstance(st, dict) and st.get("prev_ts") is not None:
        return not st.get("end_turn")
    if registry_status is not None:
        return False
    return None


def ticking_state(st):
    """True when the transcript itself is mid-turn: its last user or assistant entry did not end a
    turn. Only then is the gap since that entry sure to count, because the next entry will be a tool
    result or an assistant entry. After a turn has ended the next entry is a prompt, and a gap that
    ends at a prompt adds nothing, so a clock that ticked there (registry "busy" while background work
    runs) would later be taken back (checker, 10 Sep 23:21: WORKFLOW showed 14 h 10 m 26 s ticking,
    then 13 h 55 m 45 s fourteen minutes later). None when nothing was read."""
    if isinstance(st, dict) and st.get("prev_ts") is not None:
        return not st.get("end_turn")
    return None


def _filled(row, pid, pstart, notes, cache):
    """One row, filled on its own: an unexpected failure becomes this row's note, never the table's."""
    if pid is not None:
        try:
            _fill(row, pid, pstart, notes, cache)
        except Exception as ex:
            row.update(description="", seconds_working=0, time_text="", running_now=None, tasks_run=None)
            row.update(json.loads(json.dumps(_ROW_NEW)))
            notes.append(f"could not be read: {type(ex).__name__}: {ex}")
    row["note"] = no_em_dash("; ".join(n for n in notes if n))
    return row


def _by_terminal(tty, pids, note, cache):
    pid, pstart = _pick_pid(pids)
    try:
        name = read_registry(pid).get("name")
    except (OSError, ValueError):
        name = None
    title = name.strip() if isinstance(name, str) and name.strip() else tty
    return _filled(_row(title, tty, pid), pid, pstart, [note], cache)


# One lock for the transcript cache: the table, the waiting list (which reads his last message to
# each lane from the same cached transcript states) and the storage strip may be called from
# different threads, and two scans feeding one cached state at once would count time twice.
_ENGINE_LOCK = threading.RLock()


def conversations(w=None):
    """The table. w: a waiting() result to count each row's decisions from; when None, the most
    recent waiting() result of this process is used if one exists, else the counts stay None ("?")."""
    with _ENGINE_LOCK:
        return _conversations(w)


def _conversations(w):
    cache = _cache()
    cache.pop("_dirty", None)
    rows = []
    try:
        procs = claude_processes()
        ps_note = ""
    except (OSError, ValueError, subprocess.SubprocessError):
        procs = None
        ps_note = "process list unreadable"
    try:
        workspaces = cmux_workspaces()
        cmux_note = ""
    except (OSError, ValueError):
        workspaces = None
        cmux_note = "cmux sidebar file unreadable, listed by terminal"

    matched = set()
    if workspaces is not None:
        for ws in workspaces:
            raw = ws.get("panels")
            panels = [p for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []
            chosen = None
            for p in panels:
                tty = p.get("ttyName")
                if isinstance(tty, str) and tty and (procs is None or tty in procs):
                    chosen = p
                    break
            if chosen is None:
                continue                              # not a Claude conversation
            tty = chosen["ttyName"]
            matched.add(tty)
            pids = (procs or {}).get(tty) or [(None, None)]
            pid, pstart = _pick_pid(pids)
            row = _row(workspace_title(ws, panels[0] if panels else None), tty, pid)
            rows.append(_filled(row, pid, pstart, [ps_note] if ps_note else [], cache))
        if procs and not matched:
            # The file reads but names no live Claude terminal: its layout changed. Never a silent zero.
            rows, workspaces = [], None
            cmux_note = "cmux sidebar file has no terminal names this app can match, listed by terminal"
    if workspaces is None and procs:
        for tty in sorted(procs):
            rows.append(_by_terminal(tty, procs[tty], cmux_note, cache))
    elif procs:
        for tty in sorted(t for t in procs if t not in matched):
            rows.append(_by_terminal(tty, procs[tty], "not in the cmux sidebar", cache))
    if cache.pop("_dirty", False):
        _save_cache()
    if procs is None and not rows:
        raise RuntimeError("the process list could not be read and the cmux sidebar names no terminal")
    attach_waits(rows, w if w is not None else _recent_waiting())
    return rows


def _pick_pid(pids):
    """Several claude processes on one tty (a `claude -p` run inside a terminal): the one with a
    registry file of kind interactive, else the lowest pid (the parent)."""
    if len(pids) > 1:
        for pid, start in pids:
            try:
                if read_registry(pid).get("kind") == "interactive":
                    return pid, start
            except (OSError, ValueError, TypeError):
                pass
    return pids[0]


# ---------------------------------------------------------------------------------------------
# waiting()
# ---------------------------------------------------------------------------------------------

def _read_only_open(file, mode="r", *args, **kwargs):
    """Stands in for `open` inside queue.py: reads pass through, every write is refused."""
    if any(c in str(mode) for c in "wax+"):
        raise PermissionError(f"monitor_data is read-only toward the lab: refused to write {file}")
    return open(file, mode, *args, **kwargs)


_QUEUE = {"mod": None, "mtime": None}

# The audit-hook guard (see the READ-ONLY paragraph). Active only on the thread that set "thread",
# only while queue.py loads or builds. Writes are allowed only under WRITABLE_DIR.
WRITABLE_DIR = os.path.join(HOME, "Library/Caches/com.masondean.agents")
_GUARD = {"thread": None, "installed": False, "refused": []}
_WRITE_EVENTS = {"os.rename", "os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.chflags",
                 "os.lchflags", "os.utime", "os.truncate", "os.link", "os.symlink", "os.mkfifo", "os.mknod",
                 "os.setxattr", "os.removexattr", "shutil.rmtree", "shutil.copyfile", "shutil.copymode",
                 "shutil.copystat", "shutil.copytree", "shutil.move", "shutil.chown", "shutil.make_archive",
                 "shutil.unpack_archive"}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _writable(path):
    try:
        p = os.path.abspath(os.fsdecode(path))
    except (TypeError, ValueError):
        return False
    base = os.path.abspath(WRITABLE_DIR)
    return p == base or p.startswith(base + os.sep)


def _audit(event, args):
    if _GUARD["thread"] is None or _GUARD["thread"] != threading.get_ident():
        return
    if event == "open":
        a = tuple(args) + (None, None, None)
        path, mode, flags = a[0], a[1], a[2]
        if mode is not None:
            write = any(c in str(mode) for c in "wax+")
        else:
            write = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
        if not write:
            return
        paths = [path]
    elif event in _WRITE_EVENTS:
        paths = [a for a in args if isinstance(a, (str, bytes, os.PathLike))]
    else:
        return
    if paths and all(isinstance(p, (str, bytes, os.PathLike)) and _writable(p) for p in paths):
        return
    _GUARD["refused"].append(f"{event} {paths[0] if paths else '(no path)'}")
    raise PermissionError(f"monitor_data is read-only toward the lab: refused {event} {paths[0] if paths else ''}")


class _Guarded:
    """with _Guarded(): queue.py code runs here with every write outside the cache refused."""

    def __enter__(self):
        if not _GUARD["installed"]:
            sys.addaudithook(_audit)
            _GUARD["installed"] = True
        self.prev = _GUARD["thread"]
        _GUARD["thread"] = threading.get_ident()
        return self

    def __exit__(self, *exc):
        _GUARD["thread"] = self.prev
        return False


def _queue_module():
    mt = os.stat(QUEUE_PY).st_mtime
    if _QUEUE["mod"] is None or _QUEUE["mtime"] != mt:
        spec = importlib.util.spec_from_file_location("labqueue_monitor", QUEUE_PY)  # not "queue"
        mod = importlib.util.module_from_spec(spec)
        mod.open = _read_only_open                    # in place before any of its code runs
        saved = sys.dont_write_bytecode
        sys.dont_write_bytecode = True                # no .pyc into lab-common/__pycache__ either
        try:
            with _Guarded():
                spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = saved
        _QUEUE.update(mod=mod, mtime=mt)
    mod = _QUEUE["mod"]
    mod.open = _read_only_open                        # and reinstalled on every call
    return mod


def waiting_from_manifest(m):
    items = []
    for i in m.get("items") or []:
        bucket = i.get("bucket") or ""
        items.append({
            "id": i.get("id"),
            "text": no_em_dash(i.get("text") or ""),
            "lane": i.get("lane") or "",
            "bucket": bucket,
            "needs": NEEDS.get(bucket, bucket or "unknown"),
            "yellow": bucket != "decision",
            "source": i.get("source") or "",
            "world": i.get("world") or "",
            "world_note": no_em_dash(i.get("world_note") or ""),
        })
    stale = m.get("stale")
    unjust = unjustified_from_manifest(m)
    return {"ok": True, "message": "", "total": m.get("total"), "counts": m.get("counts"),
            "sha": m.get("sha"), "items": items, "enriched": False,
            "stale_total": len(stale) if isinstance(stale, list) else None,
            "unjustified": unjust, "unjustified_total": len(unjust)}


def unjustified_from_manifest(m):
    """queue.py's "unjustified" list (WAITING ON lines with no "because", fence 50): still asks of
    him, never counted. Each gets a stable key (queue.py gives these lines no id), its lane, its
    field and its text with em dashes as commas. Anything malformed is skipped, never raised."""
    out, seen = [], set()
    for l in m.get("unjustified") or []:
        if not isinstance(l, dict) or not isinstance(l.get("text"), str) or not l["text"].strip():
            continue
        lane = str(l.get("lane") or "")
        text = no_em_dash(l["text"])
        key = hashlib.sha1(f"{lane}|{l.get('field') or ''}|{text}".encode("utf-8")).hexdigest()[:10]
        if key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "lane": lane, "field": str(l.get("field") or ""), "text": text})
    return out


def waiting(now=None):
    with _ENGINE_LOCK:
        return _waiting(now)


def _waiting(now):
    try:
        mod = _queue_module()
        with _Guarded():
            m = mod.build()
        if not isinstance(m, dict) or not isinstance(m.get("items"), list):
            raise ValueError("build() did not return a manifest with an items list")
        w = waiting_from_manifest(m)
    except Exception as ex:                           # any failure must be SHOWN, not read as zero
        _LAST_WAITING.update(w=None, t=0.0)
        return {"ok": False,
                "message": f"The waiting list could not be read: queue.py failed ({type(ex).__name__}: {ex}).",
                "total": None, "counts": None, "sha": None, "items": [], "enriched": False}
    try:
        enrich(w, now)
    except Exception as ex:                           # the list still shows; its extra numbers say why not
        w["enrich_note"] = f"waiting times and checks could not be worked out ({type(ex).__name__}: {ex})"
    _LAST_WAITING.update(w=w, t=time.time())
    return w


# ---------------------------------------------------------------------------------------------
# Headline and summary (SPEC section 1), measured by richtext.py
# ---------------------------------------------------------------------------------------------

_RT = {"mod": None, "mtime": None}


def _richtext():
    mt = os.stat(RICHTEXT_PY).st_mtime
    if _RT["mod"] is None or _RT["mtime"] != mt:
        spec = importlib.util.spec_from_file_location("richtext_monitor", RICHTEXT_PY)
        mod = importlib.util.module_from_spec(spec)
        saved = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = saved
        _RT.update(mod=mod, mtime=mt)
    return _RT["mod"]


def _line_fields(ol, limit, rt, need_end=True):
    """need_end: the line must also end a statement to be ok (the summary). The headline passes
    HEADLINE_NEEDS_END (False since SPEC section 11): at most 50 visible characters, not code."""
    line = ol.get("line") or ""
    vis = rt.visible_text(rt.fold_line(line))
    n = ol.get("visible_len", len(vis))
    complete = bool(ol.get("complete"))
    code = bool(ol.get("code"))
    ok = bool(line) and bool(vis.strip()) and not code and n <= limit and (complete or not need_end)
    return {"text": line, "visible": vis, "visible_len": n, "limit": limit, "complete": complete,
            "over": n > limit, "ok": ok, "code": code, "needs_end": bool(need_end)}


def _after_line(md, line, rt):
    """The message after the raw line that opening_line returned, or None when it cannot be found."""
    split = getattr(rt, "_lines", None)
    trim = getattr(rt, "_trim", None) or (lambda x: x.strip().strip("\ufeff\u200b\u200c\u2060"))
    lines = split(md) if split else (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, raw in enumerate(lines):
        if trim(raw) == line:
            return "\n".join(lines[i + 1:])
    return None


def message_fields(md):
    """(headline, summary, waiting_on_you) for one message (see DEFINITIONS). Never cuts a line."""
    rt = _richtext()
    md = no_em_dash(md or "")
    first = rt.opening_line(md)
    head = _line_fields(first, HEADLINE_MAX, rt, need_end=HEADLINE_NEEDS_END)
    src, which = first, "first line"
    if head["ok"]:
        rest = _after_line(md, first["line"], rt)
        second = rt.opening_line(rest) if rest is not None else None
        if second and second.get("line"):
            src, which = second, "second line"
        else:
            which = "first line, the message has no second line"
    summ = _line_fields(src, DESC_MAX, rt, need_end=True)
    summ["from"] = which
    wo = head["visible"].lstrip().lower().startswith(WAITING_PREFIX)
    return head, summ, wo


def _message_into_row(row, text, ts, source, cut, notes):
    row.update(full_text=no_em_dash(text), full_text_ts=ts, full_text_cut=cut, text_source=source)
    try:
        head, summ, wo = message_fields(text)
        row.update(headline=head, summary=summ, waiting_on_you=wo)
    except Exception as ex:                           # the row keeps its other numbers, and says why
        row.update(headline=None, summary=None, waiting_on_you=False)
        notes.append(f"headline could not be measured ({type(ex).__name__}: {ex})")


def clock_text(seconds):
    """Time spent with seconds, for the ticking column: "13 h 34 m 07 s", "34 m 07 s", "7 s"."""
    s = max(0, int(seconds or 0))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    if h:
        return f"{h} h {m:02d} m {sec:02d} s"
    if m:
        return f"{m} m {sec:02d} s"
    return f"{sec} s"


def live_seconds(row, now=None):
    """seconds_working plus, while the transcript is mid-turn (row["ticking"]), the time since its
    last entry, capped like any other gap at GAP_CAP. Frozen otherwise, including while the registry
    says busy after a turn ended: that gap ends at a prompt and never counts (see ticking_state), so
    ticking there would show seconds that are later taken back. Never goes down between entries."""
    now = time.time() if now is None else now
    base = int(row.get("seconds_working") or 0)
    last = row.get("last_entry_ts")
    if row.get("ticking") and isinstance(last, (int, float)):
        base += int(max(0.0, min(now - last, GAP_CAP)))
    return base


def wait_text(seconds):
    """ "3 d 4 h", "4 h 12 m", "12 m 07 s", "7 s"."""
    s = max(0, int(seconds or 0))
    d, h, m, sec = s // 86400, (s % 86400) // 3600, (s % 3600) // 60, s % 60
    if d:
        return f"{d} d {h} h"
    if h:
        return f"{h} h {m} m"
    if m:
        return f"{m} m {sec:02d} s"
    return f"{sec} s"


# ---------------------------------------------------------------------------------------------
# Who owns each waiting item (SPEC section 2, delivery owner), and each row's share
# ---------------------------------------------------------------------------------------------

def _roster_sessions():
    """sessionId -> roster row, in file order."""
    with open(ROSTER) as fh:
        r = json.load(fh)
    sessions = r.get("sessions") if isinstance(r, dict) else None
    if not isinstance(sessions, dict):
        return {}
    return {k: v for k, v in sessions.items() if isinstance(v, dict)}


def live_session_ids():
    """sessionId -> pid for every Claude registry file whose process is alive."""
    out = {}
    for f in glob.glob(os.path.join(glob.escape(REGISTRY_DIR), "*.json")):
        try:
            with open(f) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        pid, sid = d.get("pid"), d.get("sessionId")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or not isinstance(sid, str) or not sid:
            continue
        try:
            os.kill(pid, 0)
        except PermissionError:
            pass                                      # alive, owned by someone else
        except OSError:
            continue
        out[sid] = pid
    return out


def item_owner_lane(item_lane, roster):
    """stack, when-home and listens items belong to WORKFLOW (lane coordinator); a status file's
    items to the roster lane whose status_file is that file, else the lane of the same name."""
    if item_lane in COORDINATOR_ITEM_LANES:
        return COORDINATOR_LANE
    for row in roster.values():
        sf = row.get("status_file")
        if isinstance(sf, str) and sf and os.path.splitext(sf)[0] == item_lane and row.get("lane"):
            return row["lane"]
    return item_lane


def owner_session(lane, roster, live):
    """The first roster session of that lane, in roster order, whose Claude process is alive."""
    for sid, row in roster.items():
        if row.get("lane") == lane and sid in live:
            return sid
    return None


def attach_waits(rows, w):
    """decisions_waiting and total_wait_seconds per row, from one waiting() result, never recounted.
    None ("?") when that result is missing or failed, or the row has no session id."""
    if not w or not w.get("ok") or not w.get("enriched"):
        return rows
    by = {}
    for it in w["items"]:
        sid = it.get("owner_session")
        if sid:
            n, s = by.get(sid, (0, 0))
            by[sid] = (n + 1, s + int(it.get("waited_seconds") or 0))
    for r in rows:
        if r.get("session_id"):
            n, s = by.get(r["session_id"], (0, 0))
            r.update(decisions_waiting=n, total_wait_seconds=s, waits_as_of=w.get("as_of"))
    return rows


# ---------------------------------------------------------------------------------------------
# Waiting time per item (SPEC section 2)
# ---------------------------------------------------------------------------------------------

_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
                "october", "november", "december")


def _month(tok):
    """Month number for "Sep", "Sept", "September" (any case), else None."""
    t = (tok or "").lower().rstrip(".")
    if len(t) < 3:
        return None
    for i, full in enumerate(_MONTH_NAMES, 1):
        if full.startswith(t):
            return i
    return None
_DATE_DM = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?(?:,?\s+(\d{1,2}):(\d)([\dxX]))?(?![\w:])")
_DATE_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)(?:[ T](\d\d):(\d\d)(?::(\d\d))?)?")
_SINCE = re.compile(r"\b(?:since|asked|opened|raised)\s+(?:on\s+)?"
                    r"(\d{1,2}\s+[A-Za-z]{3,9}\.?(?:,?\s+\d{1,2}:\d[\dxX])?|20\d\d-\d\d-\d\d(?:[ T]\d\d:\d\d(?::\d\d)?)?)",
                    re.I)
_OPEN_CELL = re.compile(r"\bOPEN\s*\(([^()]*)\)")
_HISTORY_NOTE = re.compile(r"\((?:was|previously|formerly)\b[^)]*\)*", re.I)   # queue.py's _HISTORY
# A status record's own date field as queue.py renders it: "... Asked: 2026-09-10." (render_entry writes
# every field as "<Label>: <value>."). Only at the start of the text or after a sentence end.
_FIELD_DATE = re.compile(r"(?:^|(?<=[.?!:])\s+)(When|Asked|Since|Opened|Raised|Date):\s+")
# A tag naming HIS words or question dates when he spoke, not when the lane asked him.
_HIS_WORDS_TAG = re.compile(r"\b(?:his|your|mason'?s)\b", re.I)
_LISTEN = re.compile(r"^\d+ files to hear in (.+?)(?: \[OUTSIDE the Tests and Backups tree[^\]]*\])?$", re.S)


def parse_record_date(s, now):
    """(epoch, precision) for the first date in s, or None. Local time. "7 Sep 08:4x" reads 08:40
    ("10 minutes"); "7 Sep" and "2026-09-07" read that day's midnight ("day"): always the earliest
    moment the words allow, and precision says how much later the truth can be. A day-month date
    takes this year, or last year when this year's would be more than a day ahead. A date still
    ahead of now is not a start and gives None."""
    if not isinstance(s, str):
        return None
    best = None
    m = _DATE_ISO.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh, mm, ss = m.group(4), m.group(5), m.group(6)
        prec = "second" if ss else ("minute" if hh else "day")
        best = (m.start(), [(y, mo, d, int(hh or 0), int(mm or 0), int(ss or 0))], prec)
    for m in _DATE_DM.finditer(s):
        mon = _month(m.group(2))
        if not mon:
            continue
        if best is not None and best[0] < m.start():
            break
        d = int(m.group(1))
        if m.group(3):
            hh, m1, m2 = int(m.group(3)), int(m.group(4)), m.group(5)
            prec = "10 minutes" if m2 in "xX" else "minute"
            mm = m1 * 10 + (0 if m2 in "xX" else int(m2))
        else:
            hh, mm, prec = 0, 0, "day"
        y = time.localtime(now).tm_year
        best = (m.start(), [(y, mon, d, hh, mm, 0), (y - 1, mon, d, hh, mm, 0)], prec)
        break
    if best is None:
        return None
    for (y, mo, d, hh, mm, ss) in best[1]:
        try:
            t = time.mktime((y, mo, d, hh, mm, ss, 0, 0, -1))
            if not (1 <= mo <= 12 and 1 <= d <= 31 and hh < 24 and mm < 60):
                continue
        except (OverflowError, ValueError):
            continue
        if t <= now + 86400:
            if t > now or (y < time.localtime(now).tm_year and now - t > 183 * 86400):
                return None                           # ahead of now, or a whole season back: not a start
            return (t, best[2])
    return None


def _listen_folder(text):
    m = _LISTEN.match(text or "")
    return m.group(1) if m else None


def record_start(item, stack_states, now):
    """(epoch, precision, where) from a date in the item's own record, or None (see DEFINITIONS)."""
    src, text = item.get("source") or "", item.get("text") or ""
    if src == "STACK.md":
        state = stack_states.get(item.get("id"))
        if not isinstance(state, str):
            return None
        for cell in reversed(_OPEN_CELL.findall(_HISTORY_NOTE.sub(" ", state))):
            r = parse_record_date(cell, now)
            if r:
                return r + (f"its STACK.md state cell, OPEN ({cell.strip()})",)
        return None
    if src.startswith("status/"):
        try:
            d = json.loads(text)
        except ValueError:
            d = None
        if isinstance(d, dict):
            for k in ("when", "asked", "since", "opened", "raised", "date"):
                r = parse_record_date(d.get(k), now) if isinstance(d.get(k), str) else None
                if r:
                    return r + (f'its record\'s "{k}" field, {d[k]}',)
            return None
        for m in _FIELD_DATE.finditer(text):
            rest = text[m.end():]
            d = _DATE_ISO.match(rest) or _DATE_DM.match(rest)
            if d:
                r = parse_record_date(rest[:d.end()], now)
                if r:
                    return r + (f"its record's {m.group(1)} field, {rest[:d.end()]}",)
        m = _SINCE.search(text[:160])
        if m:
            r = parse_record_date(m.group(1), now)
            if r:
                return r + (f"its record says {m.group(0).strip()}",)
        tag = _LEAD_TAG.match(text)
        if tag and not _HIS_WORDS_TAG.search(tag.group(1)):
            r = parse_record_date(tag.group(1), now)
            if r:
                return r + (f"the date in its tag [{tag.group(1).strip()}]",)
        return None
    if src == "listening folders":
        folder = _listen_folder(text)
        if folder:
            try:
                return (os.stat(folder).st_birthtime, "second", "its folder was made then")
            except (OSError, AttributeError):
                return None
    return None


def _end_of_day(t):
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 23, 59, 59, 0, 0, -1))


def wait_fields(item, first_seen, rec, now):
    """waiting_since, waited_seconds, wait_at_least, since_from, since_precision, first_seen."""
    fs = first_seen if isinstance(first_seen, (int, float)) else now
    if rec and rec[1] == "day":
        eod = _end_of_day(rec[0])
        if eod <= fs:
            start, at_least, prec = eod, True, "day"
            frm = f"{rec[2]}; a day with no time, counted from the end of that day"
        else:
            start, at_least, prec = fs, True, "second"
            frm = f"first seen by this app; its record gives only the day ({rec[2]})"
    elif rec and rec[0] <= fs:
        start, at_least, frm, prec = rec[0], False, rec[2], rec[1]
    else:
        start, at_least, prec = fs, True, "second"
        frm = "first seen by this app" + (f"; its record gives a later date ({rec[2]})" if rec else "")
    item.update(first_seen=fs, waiting_since=start, waited_seconds=max(0, int(now - start)),
                wait_at_least=at_least, since_from=frm, since_precision=prec,
                record_date=rec[0] if rec else None)


def _waits_read():
    try:
        with open(WAITS_PATH) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("first_seen"), dict):
        d = {"version": 1, "first_seen": {}, "last_seen": {}}
    if not isinstance(d.get("last_seen"), dict):
        d["last_seen"] = {}
    return d


def first_seen_update(ids, now):
    """Record now as first_seen for every id not seen before; returns id -> first_seen. The file is
    re-read right before each write and the earliest first_seen wins, so the app, the CLI and the
    tests can all write it. An id not seen for 30 days is forgotten."""
    d = _waits_read()
    fs, ls = d["first_seen"], d["last_seen"]
    changed = False
    for i in ids:
        v = fs.get(i)
        if not isinstance(v, (int, float)) or v > now + 60:
            fs[i] = now
            changed = True
        if now - (ls.get(i) if isinstance(ls.get(i), (int, float)) else 0) > 3600:
            ls[i] = now
            changed = True
    if changed:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            disk = _waits_read()
            for k, v in disk["first_seen"].items():
                if isinstance(v, (int, float)) and (k not in fs or v < fs[k]):
                    fs[k] = v
            for k, v in disk["last_seen"].items():
                if isinstance(v, (int, float)) and (k not in ls or v > ls[k]):
                    ls[k] = v
            for k in [k for k, v in ls.items() if now - v > 30 * 86400]:
                fs.pop(k, None)
                ls.pop(k, None)
            tmp = f"{WAITS_PATH}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump(d, fh, separators=(",", ":"))
            os.replace(tmp, WAITS_PATH)
        except OSError:
            pass                                      # unsaved: the next run starts these ids again
    return {i: fs[i] for i in ids if i in fs}


# ---------------------------------------------------------------------------------------------
# "May be settled": the free checks (SPEC section 2). A check that cannot run says nothing, so
# the item stays shown as open: a false "settled" hides a real item, the worse of the two errors.
# ---------------------------------------------------------------------------------------------

_CROSS_REF = re.compile(r"cross[- ]lane(?:\.md)?(?:\s+board)?[\s,:]*(?:row\s*|#\s*)?(\d{1,3})\b", re.I)
_LEAD_TAG = re.compile(r"^\s*\[([^\]]{1,120})\]")
ANSWER_KEY_LEN = 60
ANSWER_KEY_MIN = 20


def _norm(s):
    s = no_em_dash(s or "").lower().replace("\\", "")
    s = re.sub(r"[*`]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _answer_keys(item):
    keys = []
    text = item.get("text") or ""
    try:
        d = json.loads(text)
    except ValueError:
        d = None
    if isinstance(d, dict) and isinstance(d.get("question"), str):
        keys.append(_norm(d["question"])[:ANSWER_KEY_LEN])
    keys.append(_norm(text)[:ANSWER_KEY_LEN])
    return [k for k in keys if len(k) >= ANSWER_KEY_MIN]


def _ledgers():
    paths = sorted(glob.glob(os.path.join(glob.escape(LAB), "ANSWERS-*.md")))
    tl = os.environ.get("AGENTS_TEST_LEDGER")
    if tl:
        paths.append(tl)
    out = []
    for p in paths:
        try:
            with open(p, errors="replace") as fh:
                raw = fh.read()
        except OSError:
            continue
        out.append((os.path.basename(p), raw, _norm(raw)))
    return out


def parse_cross_lane(text):
    """CROSS-LANE.md: row number -> set of states seen for it ("open", "closed"). A row is closed
    when it sits under the CLOSED heading or its last cell opens with CLOSED."""
    out, closed_section = {}, False
    for line in (text or "").split("\n"):
        t = line.strip()
        if re.match(r"^#{1,6}\s", t):
            closed_section = bool(re.match(r"^#{1,6}\s*CLOSED\b", t, re.I))
            continue
        if not t.startswith("|"):
            continue
        cells = [c.strip() for c in t.strip("|").split("|")]
        if not cells or not re.match(r"^\d{1,3}$", cells[0]):
            continue
        last = next((c for c in reversed(cells) if c), "")
        state = "closed" if closed_section or re.match(r"CLOSED\b", last) else "open"
        out.setdefault(int(cells[0]), set()).add(state)
    return out


def _record_path(item):
    src = item.get("source") or ""
    if src.startswith("status/"):
        return os.path.join(LAB, src.split(":", 1)[0])
    if src.startswith("STACK.md"):
        return os.path.join(LAB, "STACK.md")
    return None


def _hhmm(t, now):
    lt, ln = time.localtime(t), time.localtime(now)
    if (lt.tm_year, lt.tm_yday) == (ln.tm_year, ln.tm_yday):
        return time.strftime("%H:%M", lt)
    return f"{lt.tm_mday} {time.strftime('%b %H:%M', lt)}"


def _lane_name(lane):
    return "WORKFLOW" if lane == COORDINATOR_LANE else (lane or "its lane")


def _settled_by_answer(item, ctx):
    keys = _answer_keys(item)
    iid = item.get("id") or ""
    for name, raw, norm in ctx.get("ledgers") or []:
        if (len(iid) >= 8 and iid in raw) or any(k in norm for k in keys):
            return f"your answer is in {name}"
    return None


def _settled_by_world(item, ctx):
    return "a file it names is gone" if item.get("world") == "STALE" else None


def cross_lane_refs(text):
    """The CROSS-LANE rows an item names as its own: only inside its leading bracket tag, the way
    lanes tag their board rows ("[STACK 23] Question: ..."). A row cited as evidence later in the
    text is not the item's row: on 10 Sep the one cross-lane mention in 51 items was such a
    citation (row 5, closed), and reading it would have hidden a live question."""
    m = _LEAD_TAG.match(text or "")
    return sorted({int(n) for n in _CROSS_REF.findall(m.group(1))}) if m else []


def _settled_by_cross_lane(item, ctx):
    refs = cross_lane_refs(item.get("text"))
    if not refs:
        return None
    board = ctx.get("cross") or {}
    if all(board.get(n) == {"closed"} for n in refs):
        return ("CROSS-LANE row " if len(refs) == 1 else "CROSS-LANE rows ") + \
            " and ".join(str(n) for n in refs) + (" is closed" if len(refs) == 1 else " are closed")
    return None


def _settled_by_silence(item, ctx):
    path = _record_path(item)
    lane = item.get("owner_lane")
    if not path or not lane:
        return None
    his = ctx["last_human"](lane)
    mt = ctx["mtime"](path)
    if his is None or mt is None or his <= mt:
        return None
    now = ctx.get("now") or time.time()
    return f"you wrote to {_lane_name(lane)} {_hhmm(his, now)}, its record is from {_hhmm(mt, now)}"


SETTLE_CHECKS = (_settled_by_answer, _settled_by_world, _settled_by_cross_lane)   # the strong checks only (SPEC 11)
HINT_CHECKS = (_settled_by_silence,)     # context for the headless checker; never a "may be settled" tag


def settle_fields(item, ctx):
    reasons = []
    for fn in SETTLE_CHECKS:
        try:
            r = fn(item, ctx)
        except Exception:
            r = None
        if r:
            reasons.append(r)
    item.update(may_be_settled=bool(reasons), settled_reason=reasons[0] if reasons else "",
                settled_reasons=reasons)


def settle_context(now):
    """Everything the free checks read, read once per waiting() call. Read-only."""
    ctx = {"now": now}
    try:
        roster = _roster_sessions()
    except (OSError, ValueError):
        roster = {}
    ctx["roster"] = roster
    ctx["live"] = live_session_ids()
    ctx["stack_states"] = {}
    try:
        mod = _queue_module()
        with open(mod.STACK) as fh:
            stack_text = fh.read()
        with _Guarded():
            srows, _ = mod.parse_stack(stack_text)
            ctx["stack_states"] = {mod.ident("STACK.md", "row" + r["row"]): r["state"] for r in srows}
    except Exception:
        pass
    ctx["ledgers"] = _ledgers()
    try:
        with open(CROSS_LANE) as fh:
            ctx["cross"] = parse_cross_lane(fh.read())
    except OSError:
        ctx["cross"] = {}
    mts, hum = {}, {}
    cache = _cache()

    def mtime(p):
        if p not in mts:
            try:
                mts[p] = os.stat(p).st_mtime
            except OSError:
                mts[p] = None
        return mts[p]

    def last_human(lane):
        if lane not in hum:
            best = None
            for sid, row in roster.items():
                if row.get("lane") != lane:
                    continue
                try:
                    path = transcript_path(sid)
                    stt = _scan(path, cache, []) if path else None
                except Exception:
                    stt = None
                t = stt.get("last_human_ts") if isinstance(stt, dict) else None
                if isinstance(t, (int, float)) and (best is None or t > best):
                    best = t
            hum[lane] = best
        return hum[lane]

    ctx["mtime"], ctx["last_human"], ctx["_cache"] = mtime, last_human, cache
    return ctx


def enrich(w, now=None, ctx=None, first_seen=None):
    """Owner, waiting time and the free checks, onto every item of a waiting() result."""
    now = time.time() if now is None else now
    if ctx is None:
        ctx = settle_context(now)
    if first_seen is None:
        first_seen = first_seen_update([i["id"] for i in w["items"] if i.get("id")], now)
    roster, live = ctx.get("roster") or {}, ctx.get("live") or {}
    for it in w["items"]:
        lane = item_owner_lane(it.get("lane") or "", roster)
        it["owner_lane"] = lane
        it["owner_session"] = owner_session(lane, roster, live)
        wait_fields(it, first_seen.get(it.get("id")), record_start(it, ctx.get("stack_states") or {}, now), now)
        settle_fields(it, ctx)
    cache = ctx.get("_cache")
    if isinstance(cache, dict) and cache.pop("_dirty", False):
        _save_cache()
    unowned = [i for i in w["items"] if not i.get("owner_session")]
    w.update(enriched=True, as_of=now, unowned=len(unowned),
             unowned_wait_seconds=sum(i["waited_seconds"] for i in unowned),
             may_be_settled_count=sum(1 for i in w["items"] if i["may_be_settled"]))
    return w


# ---------------------------------------------------------------------------------------------
# Alarms (SPEC section 5)
# ---------------------------------------------------------------------------------------------

_ALARM = {"mod": None, "mtime": None}


def _alarm_module():
    mt = os.stat(ALARM_PY).st_mtime
    if _ALARM["mod"] is None or _ALARM["mtime"] != mt:
        spec = importlib.util.spec_from_file_location("alarm_monitor", ALARM_PY)
        mod = importlib.util.module_from_spec(spec)
        saved = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = saved
        _ALARM.update(mod=mod, mtime=mt)
    return _ALARM["mod"]


def alarms(ledger=None):
    """alarm.open_alarms(): open alarms, oldest first, each a dict with id, from, why, t, when,
    acks, stale. Raises when alarm.py cannot be loaded (never an empty list standing in for that);
    a ledger that does not exist yet is no alarms, as alarm.py itself says."""
    return _alarm_module().open_alarms(ledger)


# ---------------------------------------------------------------------------------------------
# Storage (SPEC section 10)
# ---------------------------------------------------------------------------------------------

_STORE_MEM = {"sizes": {}, "tm": None, "tm_t": 0.0}


def data_volume():
    return "/System/Volumes/Data" if os.path.isdir("/System/Volumes/Data") else "/"


def free_gib(path=None):
    s = os.statvfs(path or data_volume())
    return s.f_bavail * s.f_frsize / GIB


def dir_size(path, budget_s=SCRATCH_BUDGET_S, max_entries=SCRATCH_MAX_ENTRIES):
    """Allocated bytes under path, symlinks not followed. Raises OSError when any part cannot be
    read and TimeoutError when it takes too long: a partial size is never returned."""
    end = time.monotonic() + budget_s
    st0 = os.lstat(path)
    if not stat.S_ISDIR(st0.st_mode):
        return st0.st_blocks * 512
    total, n, todo = 0, 0, [path]
    while todo:
        with os.scandir(todo.pop()) as it:
            for e in it:
                n += 1
                if n > max_entries or time.monotonic() > end:
                    raise TimeoutError(f"more than {max_entries} entries or {budget_s} s")
                if e.is_dir(follow_symlinks=False):
                    todo.append(e.path)
                else:
                    total += e.stat(follow_symlinks=False).st_blocks * 512
    return total


def parse_tmutil(text):
    """tmutil status output -> running (bool or None), phase, percent (0..100 or None)."""
    m = re.search(r"\bRunning\s*=\s*(\d+)\s*;", text or "")
    ph = re.search(r"\bBackupPhase\s*=\s*\"?([^;\"]+)\"?\s*;", text or "")
    pc = re.search(r"\bPercent\s*=\s*\"?([0-9.]+)\"?\s*;", text or "")
    pct = None
    if pc:
        try:
            v = float(pc.group(1))
            pct = round(v * 100 if v <= 1 else v, 1)
        except ValueError:
            pct = None
    return {"running": (m.group(1) != "0") if m else None, "phase": ph.group(1).strip() if ph else "",
            "percent": pct, "note": "" if m else "tmutil status gave no Running line"}


def time_machine(now=None):
    now = time.time() if now is None else now
    if _STORE_MEM["tm"] is not None and now - _STORE_MEM["tm_t"] < TM_EVERY:
        return _STORE_MEM["tm"]
    try:
        out = subprocess.run(["tmutil", "status"], capture_output=True, text=True, timeout=5)
        tm = parse_tmutil(out.stdout)
        if out.returncode != 0 and tm["running"] is None:
            tm["note"] = f"tmutil status failed ({(out.stderr or '').strip()[:80] or out.returncode})"
    except (OSError, subprocess.SubprocessError) as ex:
        tm = {"running": None, "phase": "", "percent": None, "note": f"tmutil status could not run ({_why(ex)})"}
    _STORE_MEM.update(tm=tm, tm_t=now)
    return tm


def trend(samples, now):
    """(GiB per hour or None, samples used). Least squares over the last TREND_WINDOW seconds,
    only with TREND_MIN samples or more."""
    pts = [(t, g) for t, g in samples if now - TREND_WINDOW <= t <= now + 1]
    if len(pts) < TREND_MIN:
        return None, len(pts)
    mt = sum(t for t, _ in pts) / len(pts)
    mg = sum(g for _, g in pts) / len(pts)
    var = sum((t - mt) ** 2 for t, _ in pts)
    if var <= 0:
        return None, len(pts)
    return sum((t - mt) * (g - mg) for t, g in pts) / var * 3600.0, len(pts)


def trend_text(slope):
    if slope is None:
        return ""
    if abs(slope) < STEADY_GIB_H:
        return "steady"
    return f"{'falling' if slope < 0 else 'rising'} {abs(slope):.1f} GiB an hour"


def disk_level(free):
    if free is None:
        return "unknown"
    return "red" if free < FLOOR_GIB else ("orange" if free <= ORANGE_GIB else "normal")


def _storage_read():
    try:
        with open(STORAGE_PATH) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = None
    if not isinstance(d, dict):
        d = {}
    if not isinstance(d.get("samples"), list):
        d["samples"] = []
    if not isinstance(d.get("first_size"), dict):
        d["first_size"] = {}
    d["samples"] = [s for s in d["samples"] if isinstance(s, list) and len(s) == 2
                    and all(isinstance(x, (int, float)) for x in s)]
    return d


def _storage_write(d, now):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        disk = _storage_read()
        seen = {round(t, 3) for t, _ in d["samples"]}
        d["samples"] += [s for s in disk["samples"] if round(s[0], 3) not in seen]
        d["samples"] = sorted(s for s in d["samples"] if now - s[0] <= SAMPLE_KEEP)
        for k, v in disk["first_size"].items():
            if isinstance(v, list) and len(v) == 2 and (k not in d["first_size"] or v[0] < d["first_size"][k][0]):
                d["first_size"][k] = v
        d["first_size"] = {k: v for k, v in d["first_size"].items() if now - v[0] <= 7 * 86400}
        tmp = f"{STORAGE_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(d, fh, separators=(",", ":"))
        os.replace(tmp, STORAGE_PATH)
    except OSError:
        pass


def _local_epoch(s):
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return None


def _pid_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def storage(now=None, free=None, runs=None, sizer=None, tm=None, persist=True):
    """The storage strip (see DEFINITIONS). The keyword arguments plant inputs for the controls."""
    with _ENGINE_LOCK:
        return _storage(now, free, runs, sizer, tm, persist)


def _storage(now, free, runs, sizer, tm, persist):
    now = time.time() if now is None else now
    out = {"ok": True, "message": "", "volume": data_volume(), "floor_gib": FLOOR_GIB}
    try:
        free = free_gib() if free is None else free
    except OSError as ex:
        return {"ok": False, "message": f"free space could not be read ({_why(ex)})", "free_gib": None,
                "floor_gib": FLOOR_GIB, "level": "unknown", "text": "Disk  free space could not be read"}
    d = _storage_read() if persist else {"samples": [], "first_size": {}}
    dirty = False
    if not d["samples"] or now - max(t for t, _ in d["samples"]) >= SAMPLE_EVERY:
        d["samples"].append([now, round(free, 4)])
        dirty = True
    d["samples"] = [s for s in d["samples"] if now - s[0] <= SAMPLE_KEEP]
    runs_note = ""
    if runs is None:
        try:
            with open(RUNS) as fh:
                runs = json.load(fh).get("runs") or []
        except (OSError, ValueError, AttributeError) as ex:
            runs, runs_note = [], f"runs.json could not be read ({_why(ex)}), so no running work is counted"
    sizer = sizer or dir_size
    listed, remaining_total = [], 0.0
    for r in runs:
        if not isinstance(r, dict) or r.get("state") != "running":
            continue
        key = f'{r.get("name")}|{r.get("pid")}|{r.get("started")}'
        dg = r.get("disk_gb")
        declared = float(dg) if isinstance(dg, (int, float)) and not isinstance(dg, bool) else None
        size, why = None, ""
        scratch = r.get("scratch")
        memo = _STORE_MEM["sizes"].get(key)
        if persist and memo and now - memo[0] < SCRATCH_EVERY:
            size, why = memo[1], memo[2]
        elif isinstance(scratch, str) and scratch:
            try:
                size = sizer(os.path.expanduser(scratch))
            except (OSError, TimeoutError) as ex:
                size, why = None, f"no scratch reading ({_why(ex)})"
            if persist:
                _STORE_MEM["sizes"][key] = (now, size, why)
        else:
            why = "no scratch reading (the run names no scratch folder)"
        used = None
        if size is not None:
            first = d["first_size"].get(key)
            if not (isinstance(first, list) and len(first) == 2):
                d["first_size"][key] = first = [now, size]
                dirty = True
            used = max(0.0, (size - first[1]) / GIB)
        remaining = None if declared is None else (declared if used is None else max(0.0, declared - used))
        remaining_total += remaining or 0.0
        started = _local_epoch(r.get("started"))
        hours = r.get("hours") if isinstance(r.get("hours"), (int, float)) else None
        listed.append({"name": r.get("name") or "(no name)", "lane": r.get("lane") or "", "pid": r.get("pid"),
                       "pid_alive": _pid_alive(r.get("pid")), "declared_gib": declared,
                       "used_gib": None if used is None else round(used, 3),
                       "remaining_gib": None if remaining is None else round(remaining, 3),
                       "reading": why or ("grew %.2f GiB since this app first saw it" % used),
                       "hours_left": None if (hours is None or started is None) else round(hours - (now - started) / 3600.0, 2),
                       "scratch": scratch or ""})
    declaring = [x for x in listed if x["declared_gib"]]
    after = max(0.0, free - remaining_total)
    slope, n = trend([(t, g) for t, g in d["samples"]], now)
    tmi = tm if tm is not None else time_machine(now)
    if persist and dirty:
        _storage_write(d, now)
    strip = f"Disk  {free:.1f} GiB free  |  floor {FLOOR_GIB:g}  |  "
    strip += (f"after running work  about {after:.1f} GiB, an estimate" if declaring
              else "no running work declares disk")
    out.update(free_gib=round(free, 3), level=disk_level(free), after_running_gib=round(after, 3),
               declared_remaining_gib=round(remaining_total, 3), runs=listed,
               no_running_work_declares_disk=not declaring, runs_note=runs_note,
               trend_gib_per_hour=None if slope is None else round(slope, 3), trend_text=trend_text(slope),
               trend_samples=n, trend_note="" if slope is not None else
               f"no trend yet: {n} of {TREND_MIN} samples in the last hour",
               time_machine=tmi, as_of=now, text=strip)
    return out


# The last good waiting() result, for conversations() called without one. Dropped the moment a
# waiting() call fails, and ignored once older than WAITING_MEMO_MAX, so the table's counts can
# never outlive the list they came from.
WAITING_MEMO_MAX = 180
_LAST_WAITING = {"w": None, "t": 0.0}


def _recent_waiting(now=None):
    now = time.time() if now is None else now
    w = _LAST_WAITING.get("w")
    return w if w is not None and now - (_LAST_WAITING.get("t") or 0.0) <= WAITING_MEMO_MAX else None

# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def _now_local():
    return time.strftime("%a %d %b %Y, %H:%M %Z", time.localtime())


EMPTY_TABLE = "No Claude conversations are running: no terminal has a claude process."


def render_alarms(al):
    """The alarm lines. al: {"ok", "alarms", "message"}."""
    out = []
    if not al.get("ok"):
        out.append("ALARMS: " + (al.get("message") or "could not be read"))
    elif not al.get("alarms"):
        out.append("ALARMS: none open.")
    else:
        out.append(f'ALARMS: {len(al["alarms"])} open, oldest first')
        for a in al["alarms"]:
            out.append(f'  ALARM from {a.get("from", "?")}: {a.get("why", "")}')
            acks = a.get("acks") or []
            who = ("answered by " + ", ".join(acks)) if acks else "nobody has answered yet"
            out.append(f'    {a.get("id", "?")}, raised {a.get("when", "?")}, {who}'
                       + (", open more than a day" if a.get("stale") else ""))
    return out


def _line_tags(f, limit):
    tags = []
    if f.get("over"):
        tags.append(f"over {limit}")
    if f.get("text") and not f.get("complete") and f.get("needs_end", True):
        tags.append("not a finished sentence")
    return (" (" + ", ".join(tags) + ")") if tags else ""


def render_storage(st):
    if not st:
        return []
    if not st.get("ok"):
        return ["STORAGE: " + (st.get("message") or "could not be read")]
    out = [st["text"] + f'  ({st["level"]})']
    tm = st.get("time_machine") or {}
    if tm.get("running") is None:
        tmt = "Time Machine state unknown" + (f' ({tm["note"]})' if tm.get("note") else "")
    elif tm["running"]:
        tmt = "Time Machine running" + (f', {tm["phase"]}' if tm.get("phase") else "") + \
            (f', {tm["percent"]:.1f} percent' if tm.get("percent") is not None else "")
    else:
        tmt = "Time Machine not running"
    tr = st.get("trend_text") or st.get("trend_note") or ""
    out.append(f"    trend: {tr}; {tmt}")
    for r in st.get("runs") or []:
        dec = "declares no disk" if r["declared_gib"] is None else f'declares {r["declared_gib"]:g} GiB'
        left = "" if r["hours_left"] is None else (f', {r["hours_left"]:.1f} h left' if r["hours_left"] >= 0
                                                    else f', {-r["hours_left"]:.1f} h past its hours')
        alive = "" if r["pid_alive"] is not False else f', its process {r["pid"]} is gone'
        out.append(f'    running: {r["name"]} ({r["lane"]}), {dec}, {r["reading"]}{left}{alive}')
    if st.get("runs_note"):
        out.append("    " + st["runs_note"])
    return out


def render_text(rows, w, al=None, store=None, now=None):
    now = time.time() if now is None else now
    out = []
    if al is not None:
        out += render_alarms(al)
        out.append("")
    out.append(f"AGENTS, {_now_local()}, {len(rows)} conversations")
    out.append("")
    if not rows:
        out.append(EMPTY_TABLE)
    tw = max([len("Conversation")] + [len(r["title"]) for r in rows])
    tw = min(tw, 34)
    out.append(f'{"#":>2}  {"Conversation":<{tw}}  {"Time spent":>15}  {"State":<7}  {"Running now":>11}  '
               f'{"Tasks run":>9}  {"Waiting on you":>14}  {"Total wait":>10}')
    for n, r in enumerate(rows, 1):
        run = "?" if r["running_now"] is None else str(r["running_now"])
        tot = "?" if r["tasks_run"] is None else str(r["tasks_run"])
        if r.get("time_text") and "working" in r:
            tt = clock_text(live_seconds(r, now))
        else:
            tt = r["time_text"] or "?"
        state = {True: "working", False: "waiting"}.get(r.get("working"), "?")
        dw = r.get("decisions_waiting")
        tws = r.get("total_wait_seconds")
        dws = "?" if dw is None else str(dw)
        twt = "?" if tws is None else (wait_text(tws) if dw else "none")
        out.append(f'{n:>2}  {r["title"][:tw]:<{tw}}  {tt:>15}  {state:<7}  {run:>11}  {tot:>9}  {dws:>14}  {twt:>10}')
        head, summ = r.get("headline"), r.get("summary")
        if head and head.get("text"):
            mark = "WAITING ON YOU  " if r.get("waiting_on_you") else ""
            out.append("    " + mark + head["visible"] + _line_tags(head, HEADLINE_MAX))
            if summ and summ.get("text") and summ.get("from", "").startswith("second"):
                for i, ln in enumerate(textwrap.wrap(summ["visible"] + _line_tags(summ, DESC_MAX), 96)):
                    out.append("    " + ln)
        elif r["description"]:
            for ln in textwrap.wrap(r["description"], 96):
                out.append("    " + ln)
        if r["note"]:
            out.append("    note: " + r["note"])
    out.append("")
    if store is not None:
        out += render_storage(store)
        out.append("")
    if not w["ok"]:
        out.append("WAITING ON YOU")
        out.append(w["message"])
    else:
        c = w["counts"] or {}
        more = sum(v for k, v in c.items() if k != "decision" and isinstance(v, int))
        out.append(f'{w["total"]} waiting on you. {more} need more than a decision. (queue {w["sha"]})')
        parts = [f'{c.get(b, 0)} {NEEDS[b]}' for b in ("decision", "ear", "hands", "permission", "off-machine")]
        extra = [f"{v} {k}" for k, v in c.items() if k not in NEEDS]
        out.append("By kind: " + ", ".join(parts + extra) + ". YELLOW means it needs more than reading and deciding.")
        if w.get("enriched"):
            owned = sum((r.get("decisions_waiting") or 0) for r in rows)
            lost = (w["total"] or 0) - owned
            out.append(f'{w.get("may_be_settled_count", 0)} may be settled already.'
                       + (f" {lost} belong to no conversation in the table above." if lost else ""))
        elif w.get("enrich_note"):
            out.append(w["enrich_note"])
        out.append("")
        for n, it in enumerate(w["items"], 1):
            mark = "YELLOW" if it["yellow"] else ""
            label = f'{n:>3}. {mark:<6}  {it["needs"]}, lane {it["lane"]}'
            if it.get("waited_seconds") is not None:
                label += f', waiting {"at least " if it.get("wait_at_least") else ""}{wait_text(it["waited_seconds"])}'
            if it.get("owner_lane"):
                label += f', owner {_lane_name(it["owner_lane"])}' + ("" if it.get("owner_session") else " (no live window)")
            out.append(label)
            if it.get("may_be_settled"):
                out.append("       may be settled: " + "; ".join(it.get("settled_reasons") or []))
            for para in it["text"].split("\n"):
                wrapped = textwrap.wrap(para, 96) or [""]
                for ln in wrapped:
                    out.append("       " + ln)
            out.append("")
        un = w.get("unjustified") or []
        if un:
            out.append(f"Asked of you without saying why ({len(un)}), not counted above: each line says WAITING ON "
                       "him but gives no 'because'; its lane should justify it or drop it.")
            for u in un:
                wrapped = textwrap.wrap(f'lane {u["lane"] or "?"}: {u["text"]}', 96) or [""]
                for i, ln in enumerate(wrapped):
                    out.append(("     - " if i == 0 else "       ") + ln)
            out.append("")
    return no_em_dash("\n".join(out))


def main(argv):
    if "--selftest" in argv:
        return selftest()
    try:
        al = {"ok": True, "alarms": alarms(), "message": ""}
    except Exception as ex:
        al = {"ok": False, "alarms": None,
              "message": f"the alarm list could not be read ({type(ex).__name__}: {ex})"}
    w = waiting()
    try:
        rows = conversations(w)
    except Exception as ex:
        rows = None
        err = f"The conversations could not be read: {type(ex).__name__}: {ex}"
    try:
        store = storage()
    except Exception as ex:
        store = {"ok": False, "message": f"storage could not be read ({type(ex).__name__}: {ex})"}
    if rows is None:
        if "--json" in argv:
            print(no_em_dash(json.dumps({"alarms": al, "generated": _now_local(), "conversations": None,
                                         "error": err, "storage": store, "waiting": w},
                                        ensure_ascii=False, indent=1)))
        else:
            print(no_em_dash("\n".join(render_alarms(al) + [""] + [err])))
            print(render_text([], w, store=store).split("\n", 3)[-1])
        return 1
    if "--json" in argv:
        print(no_em_dash(json.dumps(cli_payload(al, rows, store, w), ensure_ascii=False, indent=1)))
    else:
        print(render_text(rows, w, al, store))
    return 0


def cli_payload(al, rows, store, w):
    """--json: alarms FIRST, so an agent reading the top of it sees them before anything else."""
    return {"alarms": al, "generated": _now_local(), "conversations": rows, "storage": store, "waiting": w}


# ---------------------------------------------------------------------------------------------
# Planted controls
# ---------------------------------------------------------------------------------------------

def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int((t % 1) * 1000):03d}Z"


class _T:
    """Builds synthetic transcript entries in the real on-disk shapes."""

    def __init__(self, t0=1789000000.0):
        self.t0 = t0
        self.lines = []
        self.n = 0

    def _put(self, e):
        self.lines.append(json.dumps(e, separators=(",", ":")).encode() + b"\n")   # compact, as on disk

    def prompt(self, dt, text, origin=None):
        # Real shape: coordinator transcript b5c61ef5 line 284, a user entry whose content is a
        # string, with origin kind "task-notification" when it is a notification.
        e = {"parentUuid": None, "isSidechain": False, "type": "user",
             "message": {"role": "user", "content": text}, "timestamp": _iso(self.t0 + dt)}
        if origin:
            e["origin"] = {"kind": origin}
        self._put(e)

    def say(self, dt, text, model="claude-opus-5", stop=None):
        e = {"isSidechain": False, "type": "assistant", "timestamp": _iso(self.t0 + dt),
             "message": {"model": model, "role": "assistant", "content": [{"type": "text", "text": text}]}}
        if stop:
            e["message"]["stop_reason"] = stop            # real shape: "end_turn" on a turn's last entry
        self._put(e)

    def call(self, dt, name, inp, uid):
        self._put({"isSidechain": False, "type": "assistant", "timestamp": _iso(self.t0 + dt),
                   "message": {"model": "claude-opus-5", "role": "assistant",
                               "content": [{"type": "tool_use", "id": uid, "name": name, "input": inp}]}})

    def result(self, dt, uid, text, tur=None, is_error=False):
        e = {"isSidechain": False, "type": "user", "timestamp": _iso(self.t0 + dt),
             "message": {"role": "user", "content": [{"tool_use_id": uid, "type": "tool_result",
                                                        "content": text, "is_error": is_error}]}}
        if tur is not None:
            e["toolUseResult"] = tur
        self._put(e)

    def enqueue(self, dt, text):
        # Real shape: b5c61ef5 line 282, {"type":"queue-operation","operation":"enqueue",...}
        self._put({"type": "queue-operation", "operation": "enqueue", "timestamp": _iso(self.t0 + dt),
                   "content": text})

    def queued_attachment(self, dt, text):
        # Real shape: b5c61ef5, attachment type "queued_command" with the text in "prompt".
        self._put({"isSidechain": False, "type": "attachment", "timestamp": _iso(self.t0 + dt),
                   "attachment": {"type": "queued_command", "prompt": text, "commandMode": "prompt"}})

    def system(self, dt):
        self._put({"isSidechain": False, "type": "system", "subtype": "informational",
                   "timestamp": _iso(self.t0 + dt), "content": "x"})


def _bash_done(task_id, uid):
    # Modelled on transcript 96909c09: a background command completion.
    return ("<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>%s</tool-use-id>\n"
            "<output-file>/private/tmp/claude-501/-Users-masondreiling/96909c09/tasks/%s.output</output-file>\n"
            "<status>completed</status>\n<summary>Background command \"Wait for preview run to finish\" "
            "completed (exit code 0)</summary>\n</task-notification>" % (task_id, uid, task_id))


def _bash_launched(task_id):
    # Modelled on transcript 7586d3af, a Bash run_in_background result.
    return ("Command running in background with ID: %s. Output is being written to: "
            "/private/tmp/claude-501/-Users-masondreiling/7586d3af/tasks/%s.output. You will be notified "
            "when it completes. To check interim output, use Read on that file path." % (task_id, task_id))


def _monitor_started(task_id):
    # Modelled on transcript 90a06ef0, a Monitor result (its em dash kept, as an escape).
    return ("Monitor started (task %s, timeout 3600000ms). You will be notified on each event. "
            "Keep working \u2014 do not poll or sleep." % task_id)


def _run(lines, started_at=None, split=None):
    st = new_state()
    for i, ln in enumerate(lines):
        if split is not None and i == split:
            st = json.loads(json.dumps(st))          # persisted and reloaded mid-stream
        feed_line(st, ln)
    return st


def selftest():
    results = []

    def check(n, name, ok, detail, modelled=""):
        results.append(ok)
        print(f'{"PASS" if ok else "FAIL"} {n:>2}  {name}: {detail}')
        if modelled:
            print(f"        modelled on: {modelled}")

    # 1. Working time: exactly 85 s, one 2-hour wait excluded, queue and attachment noise ignored.
    T = _T()
    T.prompt(0, "go")                                     # human prompt: gap before it is waiting
    T.say(10, "Looking.")                                 # +10
    T.call(15, "Bash", {"command": "ls"}, "toolu_a1")     # +5
    T.enqueue(20, "<cross-session-message from=\"x\">hi</cross-session-message>")
    T.queued_attachment(21, "<cross-session-message from=\"x\">hi</cross-session-message>")
    T.result(45, "toolu_a1", "a\nb")                      # +30
    T.say(50, "Done.")                                    # +5   => 50
    T.system(60)
    T.enqueue(7250, _bash_done("bzzzzzzz1", "toolu_none"))
    T.prompt(7250, _bash_done("bzzzzzzz1", "toolu_none"), origin="task-notification")   # 2 h wait
    T.say(7270, "Next.")                                  # +20
    T.say(7285, "Still going.")                           # +15  => 85
    st = _run(T.lines)
    check(1, "working time", abs(st["seconds"] - 85) < 1e-6,
          f'{st["seconds"]:.3f} s counted, 85 expected; the 7200 s wait ended at a task-notification prompt',
          "b5c61ef5 line 282 (queue-operation enqueue) and line 284 (user entry, origin task-notification)")

    # 1b. The 30 minute cap: one foreground tool running 45 minutes counts 30.
    T = _T()
    T.prompt(0, "go")
    T.call(5, "Bash", {"command": "sleep"}, "toolu_c1")
    T.result(5 + 2700, "toolu_c1", "ok")
    st = _run(T.lines)
    check(2, "30 minute cap on one gap", abs(st["seconds"] - (5 + 1800)) < 1e-6,
          f'{st["seconds"]:.0f} s counted, {5 + 1800} expected for a 45 minute tool call')

    # 2. Background launch, then a terminal notification for its id: running 0, run 1.
    T = _T()
    T.prompt(0, "go")
    T.call(5, "Bash", {"command": "x", "run_in_background": True}, "toolu_b2")
    T.result(6, "toolu_b2", _bash_launched("bzh5cea68"), tur={"backgroundTaskId": "bzh5cea68"})
    T.say(7, "Waiting on it.")
    T.enqueue(300, _bash_done("bzh5cea68", "toolu_b2"))
    T.prompt(300, _bash_done("bzh5cea68", "toolu_b2"), origin="task-notification")
    st = _run(T.lines)
    r, n = running_now(st, T.t0 - 60), tasks_run(st)
    check(3, "background launch then terminal notification", r == 0 and n == 1,
          f"running {r} (expected 0), run {n} (expected 1)",
          "launch: 7586d3af 'Command running in background with ID: bzh5cea68...'; completion: "
          "96909c09 '<task-id>bhz8cvw6p</task-id><tool-use-id>...<status>completed</status>'")

    # 3. A launch with no completion, after the current process started: running 1.
    T = _T()
    T.prompt(0, "go")
    T.call(5, "Monitor", {"command": "tail -f x", "description": "d", "timeout_ms": 3600000}, "toolu_m3")
    T.result(6, "toolu_m3", _monitor_started("bo4b5z881"), tur={"taskId": "bo4b5z881"})
    # A Monitor EVENT notification (no status) must not finish it.
    ev = ("<task-notification>\n<task-id>bo4b5z881</task-id>\n<summary>Monitor event: \"lane status files\"</summary>\n"
          "<event>22:11 status changed: clip.json</event>\n</task-notification>")
    T.enqueue(30, ev)
    T.prompt(30, ev, origin="task-notification")
    st = _run(T.lines)
    r, n = running_now(st, T.t0 - 60), tasks_run(st)
    check(4, "launch with no completion, after the process started", r == 1 and n == 1,
          f"running {r} (expected 1), run {n} (expected 1); a Monitor event notification did not end it",
          "90a06ef0 'Monitor started (task bo4b5z881, timeout 3600000ms)'; event: b5c61ef5 line 282")

    # 4. The same launch, but the process started after it: running 0.
    r4 = running_now(st, T.t0 + 3600)
    check(5, "the same launch before the process started", r4 == 0 and tasks_run(st) == 1,
          f"running {r4} (expected 0), run {tasks_run(st)} (expected 1)")

    # 5. A foreground Agent call with no tool_result yet: running 1.
    T = _T()
    T.prompt(0, "go")
    T.call(5, "Agent", {"description": "Research", "prompt": "p", "subagent_type": "general-purpose"}, "toolu_f5")
    st = _run(T.lines)
    r, n = running_now(st, T.t0 - 60), tasks_run(st)
    check(6, "foreground Agent call with no result yet", r == 1 and n == 1,
          f"running {r} (expected 1), run {n} (expected 1)")

    # 5b. Async Agent: launch result, then a failed notification by agentId: running 0.
    T = _T()
    T.prompt(0, "go")
    T.call(5, "Agent", {"description": "ElectraX NKS intake leg", "prompt": "p"}, "toolu_g5")
    T.result(6, "toolu_g5", "Async agent launched successfully. (This tool result is internal metadata "
             "\u2014 never quote or paste any part of it, including the agentId below, into a user-facing reply.)\n"
             "agentId: a00207d05bb77f9d1 (internal ID - do not mention to user. Use SendMessage with to: "
             "'a00207d05bb77f9d1', summary: '<5-10 word recap>' to continue this agent.)",
             tur={"isAsync": True, "status": "async_launched", "agentId": "a00207d05bb77f9d1"})
    note = ("<task-notification>\n<task-id>a00207d05bb77f9d1</task-id>\n<tool-use-id>toolu_g5</tool-use-id>\n"
            "<output-file>/private/tmp/x/tasks/a00207d05bb77f9d1.output</output-file>\n<status>failed</status>\n"
            "<summary>Agent \"ElectraX NKS intake leg\" failed: Agent terminated early</summary>\n"
            "<note>A task-notification fires each time this agent stops.</note>\n</task-notification>")
    T.enqueue(100, note)
    T.queued_attachment(101, note)                         # delivered mid-work: still read
    st = _run(T.lines)
    mid = running_now(st, T.t0 - 60)
    # ... then SendMessage resumes it: running again, not a new task.
    T.call(200, "SendMessage", {"to": "a00207d05bb77f9d1", "message": "go on"}, "toolu_s5")
    T.result(201, "toolu_s5", "{\"success\":true,\"message\":\"Agent \\\"a00207d05bb77f9d1\\\" had no active task; "
             "resumed from transcript in the background with your message.\"}")
    st2 = _run(T.lines)
    check(7, "async agent: failed notification ends it, SendMessage resume reopens it",
          mid == 0 and running_now(st2, T.t0 - 60) == 1 and tasks_run(st2) == 1,
          f"after the notification running {mid} (expected 0); after the resume running "
          f"{running_now(st2, T.t0 - 60)} (expected 1), run {tasks_run(st2)} (expected 1)",
          "launch: 7586d3af 'Async agent launched successfully... agentId:'; failure: 96909c09 "
          "'<status>failed</status><summary>Agent \"ElectraX NKS intake leg\" failed'; resume: 0e4d0d0e "
          "'had no active task; resumed from transcript in the background'")

    # 5c. TaskStop names the id; a denied launch never started; a notification QUOTED inside a
    # tool_result must not end anything.
    T = _T()
    T.prompt(0, "go")
    T.call(5, "Monitor", {"command": "tail"}, "toolu_m6")
    T.result(6, "toolu_m6", _monitor_started("bjim87ir7"))
    T.call(7, "Bash", {"command": "y", "run_in_background": True}, "toolu_d6")
    T.result(8, "toolu_d6", "Permission for this action was denied by the Claude Code auto mode classifier.", is_error=True)
    T.call(9, "Workflow", {"script": "export const meta = {}"}, "toolu_w6")
    T.result(10, "toolu_w6", "Workflow launched in background. Task ID: we5j2pdfv\nSummary: map it",
             tur={"status": "async_launched", "taskId": "we5j2pdfv"})
    T.call(11, "Bash", {"command": "grep task-notification transcript"}, "toolu_q6")
    T.result(12, "toolu_q6", "[line 238] " + _bash_done("we5j2pdfv", "toolu_w6"))
    T.call(13, "TaskStop", {"task_id": "bjim87ir7"}, "toolu_k6")
    T.result(14, "toolu_k6", "{\"message\":\"Successfully stopped task: bjim87ir7 (tail -f x)\",\"task_id\":\"bjim87ir7\"}",
             tur={"message": "Successfully stopped task: bjim87ir7 (tail -f x)", "task_id": "bjim87ir7"})
    st = _run(T.lines)
    r, n = running_now(st, T.t0 - 60), tasks_run(st)
    check(8, "TaskStop ends a Monitor; denied launch not counted; quoted notification ignored",
          r == 1 and n == 2,
          f"running {r} (expected 1, the Workflow), run {n} (expected 2, Monitor and Workflow)",
          "TaskStop: 90a06ef0 'Successfully stopped task: bjim87ir7'; denial: 'Permission for this action "
          "was denied'; quoted notification: 1bd046f1 tool_result holding '[line 238] ... <task-notification>'; "
          "Workflow: 7586d3af 'Workflow launched in background. Task ID: we5j2pdfv'")

    # 6. Glyph stripping and customTitle.
    cases = [
        ({"processTitle": "\u2733 Dreiling_limit"}, "Dreiling_limit"),
        ({"customTitle": "Dreiling Clip", "customTitleSource": "user", "processTitle": "\u25d1 Dreiling_Clip"}, "Dreiling Clip"),
        ({"processTitle": "\u25d0 WORKFLOW"}, "WORKFLOW"),
        ({"processTitle": "\u280b Building"}, "Building"),
        ({"customTitle": "Group 1", "customTitleSource": "auto", "processTitle": "\u2733 Storage"}, "Storage"),
    ]
    got = [workspace_title(ws) for ws, _ in cases]
    check(9, "titles: glyph stripped, user customTitle wins", got == [c[1] for c in cases],
          " | ".join(f"{repr(ws.get('processTitle'))} -> {repr(g)}" for (ws, _), g in zip(cases, got)),
          "cmux session file: processTitle '\u2733 Dreiling_limit' (no customTitle), customTitle "
          "'Dreiling Clip' source user over processTitle '\u25d1 Dreiling_Clip'")

    # 7. Description: markdown stripped, cut at 200 on a word boundary.
    long_text = ("## Status\n\n**Clip lane**: the `oversampler` fix is in and the [bench](http://x) "
                 "shows *every* case passing \u2014 which settles it. " + "The remaining work " * 15 +
                 "is paperwork.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- bullet one\n```\ncode\n```")
    d = describe(long_text)
    bad = [c for c in ("**", "`", "#", "|", "[", "](", EM_DASH) if c in d]
    base = d[:-1]
    full = describe(long_text, limit=10 ** 6)             # the same text, never cut
    word_ok = d.endswith(ELLIPSIS) and full.startswith(base) and not full[len(base)].isalnum()
    short = describe("Done. Installed **v2** and ran the `selftest`. Third sentence here.")
    check(10, "description: markdown stripped, 200 max on a word boundary",
          not bad and len(d) <= 200 and word_ok and short == "Done. Installed v2 and ran the selftest.",
          f"{len(d)} chars, ends {repr(d[-30:])}; leftover markdown {bad or 'none'}; two-sentence case {repr(short)}")

    # 8. The yellow rule on a fake manifest.
    fake = {"sha": "x", "total": 5, "counts": {"decision": 1, "hands": 1, "ear": 1, "permission": 1, "off-machine": 1},
            "items": [{"id": b, "bucket": b, "lane": "t", "text": f"item {b}"}
                      for b in ("decision", "hands", "ear", "permission", "off-machine")]}
    w = waiting_from_manifest(fake)
    y = {i["bucket"]: i["yellow"] for i in w["items"]}
    ok8 = y == {"decision": False, "hands": True, "ear": True, "permission": True, "off-machine": True} \
        and w["total"] == 5 and [i["needs"] for i in w["items"]] == ["decide", "your hands", "listen", "a permission", "away from the Mac"]
    check(11, "yellow for hands, ear, permission, off-machine; never decision", ok8,
          ", ".join(f"{k} {'YELLOW' if v else 'grey'}" for k, v in y.items()),
          "queue.py BUCKETS = ('decision', 'hands', 'ear', 'permission', 'off-machine')")

    # 9. Cold versus incremental parity: every split point, state persisted through JSON.
    T1 = _T(); T1.prompt(0, "go", origin="human"); T1.say(10, "a"); T1.call(15, "Bash", {"command": "x", "run_in_background": True}, "toolu_p1")
    T1.result(16, "toolu_p1", _bash_launched("bpar00001")); T1.say(20, "b", stop="end_turn"); T1.prompt(4000, _bash_done("bpar00001", "toolu_p1"))
    T1.call(4010, "Agent", {"description": "d", "prompt": "p"}, "toolu_p2"); T1.say(4020, "final words here.", stop="end_turn")
    combo = T.lines + T1.lines                             # control 8's transcript, then this one
    whole = _run(combo)
    key = lambda s: (round(s["seconds"], 6), tasks_run(s), running_now(s, T1.t0 - 60), s["last_text"],
                     s["end_turn"], s["last_human_ts"], s["last_text_ts"], s["prev_ts"], s["last_text_cut"])
    mism = [k for k in range(len(combo) + 1) if key(_run(combo, split=k)) != key(whole)]
    # And through the real file path: a partial last line, then the rest appended.
    file_ok, file_detail = True, ""
    tdir = os.path.join(CACHE_DIR, "selftest")
    try:
        os.makedirs(tdir, exist_ok=True)
        fp = os.path.join(tdir, "parity.jsonl")
        blob = b"".join(combo)
        cut = len(b"".join(combo[:5])) + 17                # mid-line
        with open(fp, "wb") as fh:
            fh.write(blob[:cut])
        ent, _ = scan_file(fp, None)
        ent = json.loads(json.dumps(ent))
        with open(fp, "ab") as fh:
            fh.write(blob[cut:])
        ent, _ = scan_file(fp, ent)
        file_ok = key(ent["state"]) == key(whole) and ent["offset"] == len(blob)
        # A rewritten (shrunk) file is recomputed from zero.
        with open(fp, "wb") as fh:
            fh.write(b"".join(combo[:3]))
        ent2, _ = scan_file(fp, ent)
        file_ok = file_ok and key(ent2["state"]) == key(_run(combo[:3]))
        file_detail = f"file path with a partial line and a shrink: {'same' if file_ok else 'DIFFERENT'}"
    except OSError as ex:
        file_ok, file_detail = False, f"file path check could not run: {ex}"
    finally:
        try:
            for f in glob.glob(os.path.join(tdir, "*")):
                os.remove(f)
            os.rmdir(tdir)
        except OSError:
            pass
    check(12, "cold and incremental reads agree", not mism and file_ok,
          f"{len(combo) + 1} split points, {len(mism)} disagree; {file_detail}")

    # 10. queue.py stays read-only: its manifest file is untouched by waiting().
    mf = os.path.join(LAB, ".queue-manifest.json")
    before = os.stat(mf).st_mtime if os.path.exists(mf) else None
    refused = False
    try:
        _read_only_open(os.path.join(CACHE_DIR, "never"), "w")
    except PermissionError:
        refused = True
    wq = waiting()
    after = os.stat(mf).st_mtime if os.path.exists(mf) else None
    check(13, "queue.py loaded read-only", refused and before == after and wq["ok"],
          f"write refused {refused}; lab-common/.queue-manifest.json mtime unchanged {before == after}; "
          f"queue.py ran {wq['ok']} ({wq['total']} items)" if wq["ok"] else wq["message"])

    # 11. No em dash reaches the CLI text.
    demo_rows = [{"title": "t", "description": describe("It works \u2014 finally."), "seconds_working": 0,
                  "time_text": "under 1 m", "running_now": 0, "tasks_run": 0, "session_id": "s", "pid": 1,
                  "tty": "ttys000", "note": ""}]
    txt = render_text(demo_rows, waiting_from_manifest({"total": 1, "counts": {"decision": 1}, "sha": "x",
                                                        "items": [{"bucket": "decision", "lane": "t", "text": "a \u2014 b"}]}))
    check(14, "no em dash in CLI output", EM_DASH not in txt and "It works, finally." in txt,
          f"description became {repr(demo_rows[0]['description'])}")

    # 12. time text format.
    tt = [time_text(s) for s in (0, 59, 60, 45 * 60, 12 * 3600 + 40 * 60 + 59)]
    check(15, "time text", tt == ["under 1 m", "under 1 m", "1 m", "45 m", "12 h 40 m"], " | ".join(tt))

    # 16. A foreground Bash call moved to the background after its timeout: both wordings, with and
    # without toolUseResult, then its terminal notification. Output that QUOTES the phrase is not a launch.
    moved = ("Command did not complete within its 120s timeout and was moved to the background (ID: b38mbyewb). "
             "Output is being written to: /private/tmp/claude-501/-Users-masondreiling/42e71f59-d436-4167-8e5e-"
             "f9bedd0dc067/tasks/b38mbyewb.output. You will be notified when it completes. To check interim "
             "output, use Read on that file path.")
    T = _T()
    T.prompt(0, "go")
    T.call(5, "Bash", {"command": "python3 long.py", "timeout": 120000}, "toolu_t16")
    T.result(125, "toolu_t16", moved, tur={"stdout": "", "stderr": "", "interrupted": False, "isImage": False,
                                           "noOutputExpected": False, "backgroundTaskId": "b38mbyewb",
                                           "timedOutAfterMs": 120000})
    T.call(130, "Bash", {"command": "python3 other.py"}, "toolu_u16")
    T.result(250, "toolu_u16", moved.replace("b38mbyewb", "bregex001"))          # no toolUseResult: text path
    T.call(260, "Bash", {"command": "grep moved transcript"}, "toolu_q16")
    T.result(261, "toolu_q16", "[line 1032] " + moved.replace("b38mbyewb", "bquoted01"))
    mid = _run(T.lines)
    r_mid, n_mid = running_now(mid, T.t0 - 60), tasks_run(mid)
    T.enqueue(600, _bash_done("b38mbyewb", "toolu_t16"))
    T.prompt(600, _bash_done("b38mbyewb", "toolu_t16"), origin="task-notification")
    T.prompt(700, _bash_done("bregex001", "toolu_u16"), origin="task-notification")
    end = _run(T.lines)
    r_end, n_end = running_now(end, T.t0 - 60), tasks_run(end)
    check(16, "foreground Bash moved to the background after its timeout", (r_mid, n_mid, r_end, n_end) == (2, 2, 0, 2),
          f"before the notifications running {r_mid} (expected 2), run {n_mid} (expected 2, the quoted one not "
          f"counted); after them running {r_end} (expected 0), run {n_end} (expected 2)",
          "42e71f59 line 1032 'Command did not complete within its 120s timeout and was moved to the background "
          "(ID: b38mbyewb)' with toolUseResult backgroundTaskId; its notification at line 1049")

    # 17. Description: a lead-in ending in a colon joins the next sentence; a list number inside bold goes.
    lead = describe("Everything you answered is handled or ready. Summary:\n\n**1. The drive has all 7 Nexus "
                    "originals, so nothing was lost.** Six are in the 8 September backup.")
    want17 = "Everything you answered is handled or ready. Summary: The drive has all 7 Nexus originals, so nothing was lost."
    plain = describe("Your answers, in order:\n\n**2. Tags are fixed.** More.")
    check(17, "description: a colon lead-in joins the next sentence, bold list numbers removed",
          lead == want17 and plain == "Your answers, in order: Tags are fixed. More.",
          f"{lead!r}; {plain!r}", "Preset Library's last message, 10 Sep 2026 20:30: 'Everything you answered is "
          "handled or ready. Summary:' then '**1. The drive has all 7 Nexus originals...'")

    # 18. The write guard around queue.py: every write route refused outside the allowed folder, allowed
    # inside it. Everything here happens inside the cache folder: the allowed folder is narrowed for the test.
    global QUEUE_PY, WRITABLE_DIR
    gdir = os.path.join(CACHE_DIR, "selftest", "guard")
    saved_q, saved_w, saved_mod = QUEUE_PY, WRITABLE_DIR, dict(_QUEUE)
    detail18, ok18 = "", False
    try:
        import shutil as _sh
        _sh.rmtree(gdir, ignore_errors=True)
        os.makedirs(os.path.join(gdir, "allowed"))
        os.makedirs(os.path.join(gdir, "outside"))
        keep = os.path.join(gdir, "outside", "keep.txt")
        with open(keep, "w") as fh:
            fh.write("keep")
        fake = os.path.join(gdir, "queue.py")
        with open(fake, "w") as fh:
            fh.write(textwrap.dedent(f"""
                import os, pathlib, tempfile, shutil
                OUT = {os.path.join(gdir, "outside")!r}
                OK = {os.path.join(gdir, "allowed")!r}
                def build():
                    tries = [
                        ("pathlib", lambda: pathlib.Path(OUT, "p.txt").write_text("x")),
                        ("io.open", lambda: __import__("io").open(os.path.join(OUT, "i.txt"), "w").close()),
                        ("os.open", lambda: os.close(os.open(os.path.join(OUT, "o.txt"), os.O_WRONLY | os.O_CREAT, 0o644))),
                        ("tempfile", lambda: tempfile.mkstemp(dir=OUT)),
                        ("os.replace", lambda: os.replace(os.path.join(OUT, "keep.txt"), os.path.join(OUT, "moved.txt"))),
                        ("os.remove", lambda: os.remove(os.path.join(OUT, "keep.txt"))),
                        ("os.mkdir", lambda: os.mkdir(os.path.join(OUT, "d"))),
                        ("shutil.copy", lambda: shutil.copy(os.path.join(OUT, "keep.txt"), os.path.join(OUT, "c.txt"))),
                    ]
                    out = []
                    for name, fn in tries:
                        try:
                            fn(); out.append(name + " WROTE")
                        except PermissionError:
                            out.append(name + " refused")
                        except OSError as ex:
                            out.append(name + " WROTE or failed: " + type(ex).__name__)
                    try:
                        pathlib.Path(OK, "fine.txt").write_text("x"); out.append("allowed folder written")
                    except PermissionError:
                        out.append("allowed folder refused")
                    return {{"items": [{{"id": o, "text": o, "bucket": "decision", "lane": "t"}} for o in out],
                            "total": len(out), "counts": {{"decision": len(out)}}, "sha": "guard"}}
                """))
        QUEUE_PY, WRITABLE_DIR = fake, os.path.join(gdir, "allowed")
        _QUEUE.update(mod=None, mtime=None)
        wg = waiting()
        got = [i["text"] for i in wg["items"]] if wg["ok"] else [wg["message"]]
        left = sorted(os.listdir(os.path.join(gdir, "outside")))
        try:
            with open(keep) as fh:
                kept = fh.read() == "keep"
        except OSError:
            kept = False
        wrote = [g for g in got if "WROTE" in g]
        ok18 = (wg["ok"] and len(got) == 9 and not wrote and got[-1] == "allowed folder written"
                and left == ["keep.txt"] and kept)
        detail18 = (f"{sum(1 for g in got if g.endswith('refused'))} of 8 write routes refused"
                    f"{', WROTE: ' + ', '.join(wrote) if wrote else ''}; {got[-1] if got else ''}; outside folder "
                    f"holds {left}, keep.txt intact {kept}")
    except Exception as ex:
        detail18 = f"could not run: {type(ex).__name__}: {ex}"
    finally:
        QUEUE_PY, WRITABLE_DIR = saved_q, saved_w
        _QUEUE.clear(); _QUEUE.update(saved_mod)
        import shutil as _sh
        _sh.rmtree(gdir, ignore_errors=True)
    check(18, "queue.py cannot write by any route (pathlib, io, os.open, tempfile, replace, remove, mkdir, copy)",
          ok18, detail18, "checker's qfaults.py: a build() that wrote through pathlib got past the open() guard")

    # 19. A small fake world (cmux file, registry, transcripts, cache), all inside the cache folder.
    wdir = os.path.join(CACHE_DIR, "selftest", "world")
    names = ("CMUX_SESSION", "REGISTRY_DIR", "PROJECTS_DIR", "STATE_PATH", "ROSTER", "STATUS_DIR",
             "claude_processes", "transcript_path")
    saved_g = {k: globals()[k] for k in names}
    saved_mem, saved_tp = dict(_MEM), dict(_TRANSCRIPT_PATHS)
    out19 = {}
    try:
        import shutil as _sh
        _sh.rmtree(wdir, ignore_errors=True)
        for d in ("reg", "proj/p", "status"):
            os.makedirs(os.path.join(wdir, d))
        t0 = 1789000000.0
        with open(os.path.join(wdir, "reg", "900001.json"), "w") as fh:
            json.dump({"pid": 900001, "sessionId": "selftest-s1", "name": "World one", "startedAt": (t0 - 60) * 1000}, fh)
        with open(os.path.join(wdir, "reg", "900002.json"), "w") as fh:
            fh.write("[1]")                                             # valid JSON, wrong shape
        with open(os.path.join(wdir, "roster.json"), "w") as fh:
            json.dump({"sessions": {}}, fh)
        T = _T(t0)
        T.prompt(0, "go"); T.say(10, "World row one is fine.")
        T.call(15, "Bash", {"command": "x", "run_in_background": True}, "toolu_w19")
        T.result(16, "toolu_w19", _bash_launched("bworld001"), tur={"backgroundTaskId": "bworld001"})
        with open(os.path.join(wdir, "proj/p", "selftest-s1.jsonl"), "wb") as fh:
            fh.write(b"".join(T.lines))
        globals().update(CMUX_SESSION=os.path.join(wdir, "cmux.json"), REGISTRY_DIR=os.path.join(wdir, "reg"),
                         PROJECTS_DIR=os.path.join(wdir, "proj"), STATE_PATH=os.path.join(wdir, "state.json"),
                         ROSTER=os.path.join(wdir, "roster.json"), STATUS_DIR=os.path.join(wdir, "status"),
                         claude_processes=lambda: {"ttys900": [(900001, t0 - 60)], "ttys901": [(900002, t0 - 60)]})

        def world(cmux_text):
            with open(os.path.join(wdir, "cmux.json"), "w") as fh:
                fh.write(cmux_text)
            _MEM.update(state=None, disk_mtime=None)
            _TRANSCRIPT_PATHS.clear()
            return [(r["title"], r["tty"], r["running_now"], r["tasks_run"], r["note"]) for r in conversations()]

        renamed = json.dumps({"windows": [{"tabManager": {"workspaces": [
            {"processTitle": "✳ World one", "panels": [{"tty": "ttys900"}]}]}}]})
        partial = json.dumps({"windows": [{"tabManager": {"workspaces": [
            {"processTitle": "✳ World one", "panels": [{"ttyName": "ttys900"}]},
            {"customTitle": "Group 1", "customTitleSource": "auto", "panels": [{"ttyName": "ttys950"}]}]}}]})
        out19["renamed"] = world(renamed)
        out19["partial"] = world(partial)
        out19["list"] = world("[1,2]")
        out19["null window"] = world('{"windows":[null]}')
        # a cache entry missing its state: recomputed, same numbers
        with open(os.path.join(wdir, "state.json")) as fh:
            d = json.load(fh)
        for ent in d["files"].values():
            ent.pop("state", None)
        with open(os.path.join(wdir, "state.json"), "w") as fh:
            json.dump(d, fh)
        out19["bad cache entry"] = world(partial)
        # one row failing unexpectedly: only that row gets a note
        def boom(sid):
            raise RuntimeError("planted")
        globals()["transcript_path"] = boom
        out19["row failure"] = world(partial)
    except Exception as ex:
        out19["error"] = f"{type(ex).__name__}: {ex}"
    finally:
        globals().update(saved_g)
        _MEM.clear(); _MEM.update(saved_mem)
        _TRANSCRIPT_PATHS.clear(); _TRANSCRIPT_PATHS.update(saved_tp)
        import shutil as _sh
        _sh.rmtree(wdir, ignore_errors=True)
    reg_bad = "Claude registry file for pid 900002 unreadable (not a JSON object (list))"
    exp19 = {
        "renamed": [("World one", "ttys900", 1, 1, "cmux sidebar file has no terminal names this app can match, listed by terminal"),
                    ("ttys901", "ttys901", None, None, "cmux sidebar file has no terminal names this app can match, listed by terminal; " + reg_bad)],
        "partial": [("World one", "ttys900", 1, 1, ""),
                    ("ttys901", "ttys901", None, None, "not in the cmux sidebar; " + reg_bad)],
        "list": [("World one", "ttys900", 1, 1, "cmux sidebar file unreadable, listed by terminal"),
                 ("ttys901", "ttys901", None, None, "cmux sidebar file unreadable, listed by terminal; " + reg_bad)],
        "null window": [("World one", "ttys900", 1, 1, "cmux sidebar file has no terminal names this app can match, listed by terminal"),
                        ("ttys901", "ttys901", None, None, "cmux sidebar file has no terminal names this app can match, listed by terminal; " + reg_bad)],
        "bad cache entry": [("World one", "ttys900", 1, 1, ""),
                            ("ttys901", "ttys901", None, None, "not in the cmux sidebar; " + reg_bad)],
        "row failure": [("World one", "ttys900", None, None, "could not be read: RuntimeError: planted"),
                        ("ttys901", "ttys901", None, None, "not in the cmux sidebar; " + reg_bad)],
    }
    bad19 = [k for k in exp19 if out19.get(k) != exp19[k]]
    check(19, "fake world: cmux layout change, partial match, bad shapes, bad cache entry, one row failing",
          not bad19 and "error" not in out19,
          f"{len(exp19) - len(bad19)} of {len(exp19)} cases as expected"
          + (f"; first wrong: {bad19[0]} gave {out19.get(bad19[0])}" if bad19 else "")
          + (f"; {out19['error']}" if "error" in out19 else ""),
          "checker's faults2.py (ttyName renamed: 0 rows, no note) and faults.py (list registry, windows [null], "
          "cache entry without state)")

    # ---- SPEC sections 1, 2, 5, 6 and 10: the new numbers, each with a planted control ----------
    import shutil as _sh
    sdir = os.path.join(CACHE_DIR, "selftest", "new")
    _sh.rmtree(sdir, ignore_errors=True)
    os.makedirs(sdir, exist_ok=True)
    now0 = time.mktime((2026, 9, 10, 22, 0, 0, 0, 0, -1))          # Thu 10 Sep 2026 22:00 local

    # 20. Headline (50) and summary (200): never cut, "over" flagged, second line when the first is the headline.
    got20, bad20 = {}, []
    try:
        long2 = "The second line runs long on purpose " + "and keeps going " * 13 + "until it ends here."
        cases = {
            "headline then summary": ("**Done.** Installed.\n\nThe second line tells the story in full.",
                                      dict(h_ok=True, h_len=16, s_text="The second line tells the story in full.", s_over=False)),
            "exactly 50": ("A" * 49 + ".", dict(h_ok=True, h_len=50, h_over=False)),
            "51 is over": ("A" * 50 + ".", dict(h_ok=False, h_len=51, h_over=True, h_text="A" * 50 + ".")),
            "long first line, never cut": ("This headline runs well past the fifty character limit on purpose.\nSecond.",
                                           dict(h_ok=False, h_over=True, s_text="This headline runs well past the fifty character limit on purpose.")),
            "not finished, still a headline (SPEC 11)": ("Summary:\nThe rest.", dict(h_ok=True, h_complete=False, h_over=False)),
            "summary over 200": ("Short one.\n" + long2, dict(h_ok=True, s_over=True, s_text=long2, s_complete=True)),
            "no second line": ("Done.", dict(h_ok=True, s_text="Done.", s_from="first line, the message has no second line")),
            "waiting on you, bold": ("**Waiting on you:** approve the install.", dict(wo=True, h_ok=True)),
            "waiting on you, not at the start": ("Nothing is waiting on you: all done.", dict(wo=False)),
        }
        for name, (md_, want) in cases.items():
            h, sm, wo = message_fields(md_)
            have = dict(h_ok=h["ok"], h_len=h["visible_len"], h_over=h["over"], h_text=h["text"], h_complete=h["complete"],
                        s_text=sm["text"], s_over=sm["over"], s_complete=sm["complete"], s_from=sm["from"], wo=wo)
            got20[name] = {k: have[k] for k in want}
            if got20[name] != want:
                bad20.append(name)
        err20 = ""
    except Exception as ex:
        err20 = f"{type(ex).__name__}: {ex}"
    check(20, "headline 50 and summary 200: over flagged never cut, second line after a headline, 'Waiting on you:'",
          not bad20 and not err20, f"{len(got20) - len(bad20)} of {len(cases)} cases as expected"
          + (f"; first wrong: {bad20[0]} gave {got20[bad20[0]]}" if bad20 else "") + (f"; {err20}" if err20 else ""),
          "SPEC section 1: 'A line over its limit is NEVER cut silently'; section 0 item 13")

    # 21. Working or waiting, and the ticking clock.
    T = _T(now0 - 600)
    T.prompt(0, "go", origin="human")
    T.say(5, "Looking.")
    T.call(10, "Bash", {"command": "ls"}, "toolu_w21")
    s_tool = _run(T.lines)                                  # last entry a tool call: working
    T.result(12, "toolu_w21", "ok")
    T.say(20, "Done.", stop="end_turn")
    s_end = _run(T.lines)                                   # a turn ended: waiting
    T.prompt(30, "<local-command-stdout>model set</local-command-stdout>")
    s_local = _run(T.lines)                                 # a local slash command starts no turn
    T.prompt(40, _bash_done("bw2100001", "toolu_none"), origin="task-notification")
    s_note = _run(T.lines)                                  # a notification wakes it: working
    T.say(50, "Seen.", stop="end_turn")
    T.prompt(60, "keep going", origin="human")
    T.prompt(61, "[Request interrupted by user]")
    s_int = _run(T.lines)                                   # he pressed Escape: waiting
    ws = [working_state("idle", x) for x in (s_tool, s_end, s_local, s_note, s_int)]
    busy = working_state("busy", s_end)
    none = working_state(None, None)
    r21 = {"seconds_working": 100, "working": True, "ticking": True, "last_entry_ts": now0 - 50}
    ticks = (live_seconds(r21, now0), live_seconds(dict(r21, last_entry_ts=now0 - 5000), now0),
             live_seconds(dict(r21, working=False, ticking=False), now0))
    clocks = (clock_text(13 * 3600 + 34 * 60 + 7), clock_text(65), clock_text(7))
    ok21 = (ws == [True, False, False, True, False] and busy is True and none is None
            and ticks == (150, 100 + GAP_CAP, 100) and clocks == ("13 h 34 m 07 s", "1 m 05 s", "7 s"))
    check(21, "working or waiting from the registry and the last entry; the clock ticks only while working",
          ok21, f"tool call, end of turn, local command, notification, Escape -> {ws} (expected [True, False, False, "
          f"True, False]); registry busy {busy}; nothing read {none}; ticks {ticks} (expected (150, {100 + GAP_CAP}, 100)); "
          f"{' | '.join(clocks)}", "coordinator transcript b5c61ef5, 10 Sep: stop_reason end_turn on the turn's last "
          "entries; registry status busy, idle or shell")

    # 22. His last message: only a prompt with origin kind "human" counts.
    T = _T(now0 - 900)
    T.prompt(0, "first words", origin="human")
    T.say(5, "ok", stop="end_turn")
    T.prompt(100, "<cross-session-message from=\"x\">hi</cross-session-message>", origin="peer")
    T.prompt(200, _bash_done("bw2200001", "toolu_none"), origin="task-notification")
    T.prompt(300, "no origin at all")
    st22 = _run(T.lines)
    T.prompt(400, "second words", origin="human")
    st22b = _run(T.lines)
    ok22 = st22["last_human_ts"] == T.t0 and st22b["last_human_ts"] == T.t0 + 400
    check(22, "his last message counts only origin kind human", ok22,
          f"after a peer message, a notification and an unlabelled prompt: {st22['last_human_ts'] - T.t0 if st22['last_human_ts'] else None} s "
          f"(expected 0); after his second message: {st22b['last_human_ts'] - T.t0 if st22b['last_human_ts'] else None} s (expected 400)",
          "10 Sep, 12 recent transcripts: 819 prompts origin human, 763 peer, 474 task-notification")

    # 23. The full latest message is kept whole (hover), with its own timestamp.
    T = _T(now0 - 300)
    big = ("## Report\n\n" + "A long line of the report that the hover must show whole. " * 160).strip()
    T.prompt(0, "go", origin="human")
    T.say(10, big)
    T.call(20, "Bash", {"command": "ls"}, "toolu_x23")          # a later tool call does not replace it
    st23 = _run(T.lines)
    huge = "x" * (TEXT_CAP + 10)
    T.say(30, huge)
    st23b = _run(T.lines)
    ok23 = (st23["last_text"] == big and not st23["last_text_cut"] and st23["last_text_ts"] == T.t0 + 10
            and len(st23b["last_text"]) == TEXT_CAP and st23b["last_text_cut"] and st23b["last_text_ts"] == T.t0 + 30)
    check(23, "the latest message kept whole for the hover, with its timestamp; the cap is said, not silent", ok23,
          f"{len(big)} characters kept {len(st23['last_text'] or '')}, cut {st23['last_text_cut']}, stamp +{(st23['last_text_ts'] or 0) - T.t0:.0f} s "
          f"(expected +10); a {TEXT_CAP + 10} character message kept {len(st23b['last_text'] or '')}, cut {st23b['last_text_cut']}",
          "engine version 4 kept only the first 4000 characters")

    # 24. first_seen in the cache (earliest wins) and the backfill from the item's own record.
    global WAITS_PATH
    saved_wp = WAITS_PATH
    detail24, ok24 = "", False
    try:
        WAITS_PATH = os.path.join(sdir, "waits.json")
        a = first_seen_update(["a", "b"], 1000.0)
        b = first_seen_update(["a", "c"], 2000.0)
        with open(WAITS_PATH) as fh:
            dd = json.load(fh)
        dd["first_seen"]["a"] = 500.0                        # another process saw "a" earlier
        with open(WAITS_PATH, "w") as fh:
            json.dump(dd, fh)
        c = first_seen_update(["a", "d"], 3000.0)
        fs_ok = a == {"a": 1000.0, "b": 1000.0} and b == {"a": 1000.0, "c": 2000.0} and c == {"a": 500.0, "d": 3000.0}
        sid20 = "row20id"
        states = {sid20: "OPEN (6 Sep 19:46); recommendation: go | || SECURITY GATE ADDED 7 Sep 04:03",
                  "row27id": "AMENDED 7 Sep 04:30, a hole; OPEN (7 Sep 07:4x) (was OPEN (5 Sep 10:00))",
                  "row26id": "OPEN, a product question"}
        folder = os.path.join(sdir, "Hear It - planted folder")
        os.makedirs(folder)
        born = os.stat(folder).st_birthtime
        items24 = [
            ({"id": sid20, "source": "STACK.md", "text": "[row 20] x"}, (time.mktime((2026, 9, 6, 19, 46, 0, 0, 0, -1)), "minute")),
            ({"id": "row27id", "source": "STACK.md", "text": "[row 27] x"}, (time.mktime((2026, 9, 7, 7, 40, 0, 0, 0, -1)), "10 minutes")),
            ({"id": "row26id", "source": "STACK.md", "text": "[row 26] x"}, None),
            ({"id": "e1", "source": "status/eq.json:decisions_for_mason",
              "text": json.dumps({"asked": "2026-09-10", "question": "V2 plan?"})}, (time.mktime((2026, 9, 10, 0, 0, 0, 0, 0, -1)), "day")),
            ({"id": "s1", "source": "status/sampler.json:decisions_for_mason",
              "text": "[LISTEN, since 7 Sep, never boarded] Question: do you hear the holes, from his 2 Sep words?"},
             (time.mktime((2026, 9, 7, 0, 0, 0, 0, 0, -1)), "day")),
            ({"id": "s2", "source": "status/eq.json:next",
              "text": "FROM THE AUDIT: his sequencing order of 2 Sep 19:18 still holds"}, None),
            ({"id": "s3", "source": "status/eq.json:next", "text": "[ASKED 25 Sep] a date ahead of now"}, None),
            ({"id": "s4", "source": "status/sampler.json:decisions_for_mason",
              "text": "[AAX, his presets question, 10 Sep] Question: openable outside Maschine?"}, None),
            ({"id": "s6", "source": "status/sampler.json:decisions_for_mason",
              "text": "[IDEA, his 8 Sep words] Question: when you said 'start flat', did you mean the knob?"}, None),
            ({"id": "s7", "source": "status/sampler.json:decisions_for_mason",
              "text": "[ASKED 8 Sep, never boarded] Question: a private GitHub copy?"},
             (time.mktime((2026, 9, 8, 0, 0, 0, 0, 0, -1)), "day")),
            ({"id": "e2", "source": "status/eq.json:decisions_for_mason",
              "text": "V2 plan: go as written, or change something first? Options: Go; Change. Asked: 2026-09-10."},
             (time.mktime((2026, 9, 10, 0, 0, 0, 0, 0, -1)), "day")),
            ({"id": "e3", "source": "status/eq.json:decisions_for_mason",
              "text": "When the key changes, should an EQ move too? Options: A; B."}, None),
            ({"id": "s5", "source": "status/sampler.json:decisions_for_mason",
              "text": "[STACK 23] Question: an ear first? His 2 Sep words say so."}, None),
            ({"id": "l1", "source": "listening folders",
              "text": f"3 files to hear in {folder} [OUTSIDE the Tests and Backups tree, fence 12]"}, (born, "second")),
        ]
        rec_bad = []
        for it, want in items24:
            r = record_start(it, states, now0)
            if (r[:2] if r else None) != want:
                rec_bad.append(f"{it['id']} gave {r[:2] if r else None}")
        rollover = parse_record_date("since 28 Dec", time.mktime((2027, 1, 3, 9, 0, 0, 0, 0, -1)))
        roll_ok = rollover is not None and rollover[0] == time.mktime((2026, 12, 28, 0, 0, 0, 0, 0, -1))
        w1, w2, w3 = {}, {}, {}
        rec = (now0 - 5 * 86400, "minute", "planted record")
        wait_fields(w1, now0 - 3600, rec, now0)               # record earlier than first_seen: the record
        wait_fields(w2, now0 - 3600, None, now0)              # no record: first_seen, "at least"
        wait_fields(w3, now0 - 3600, (now0 - 60, "minute", "later"), now0)   # record later: first_seen, "at least"
        # A bare day three days back: counted from the END of that day, "at least". The same day as
        # first_seen: first_seen, "at least". Never that day's midnight (the 10 Sep 23:46 checker saw
        # questions first written at 19:08 shown as waiting 23 h 46 m).
        w4, w5 = {}, {}
        d3 = _end_of_day(now0 - 3 * 86400)
        wait_fields(w4, now0 - 3600, (d3 - 86399, "day", "planted day"), now0)
        wait_fields(w5, now0 - 60, (_end_of_day(now0 - 60) - 86399, "day", "planted day"), now0)
        wf_ok = ((w1["waited_seconds"], w1["wait_at_least"]) == (5 * 86400, False)
                 and (w2["waited_seconds"], w2["wait_at_least"]) == (3600, True)
                 and (w3["waited_seconds"], w3["wait_at_least"]) == (3600, True) and "later" in w3["since_from"]
                 and (w4["waited_seconds"], w4["wait_at_least"]) == (int(now0 - d3), True)
                 and (w5["waited_seconds"], w5["wait_at_least"]) == (60, True))
        ok24 = fs_ok and not rec_bad and roll_ok and wf_ok
        detail24 = (f"first_seen kept and earliest wins {fs_ok}; record dates {len(items24) - len(rec_bad)} of {len(items24)} right"
                    + (f" ({'; '.join(rec_bad)})" if rec_bad else "") + f"; 28 Dec read on 3 Jan is last year {roll_ok}; "
                    f"record, first_seen and later-record waits {w1['waited_seconds']}/{w1['wait_at_least']}, "
                    f"{w2['waited_seconds']}/{w2['wait_at_least']}, {w3['waited_seconds']}/{w3['wait_at_least']}; "
                    f"a bare day 3 days back and today {w4['waited_seconds']}/{w4['wait_at_least']}, "
                    f"{w5['waited_seconds']}/{w5['wait_at_least']}")
    except Exception as ex:
        detail24 = f"could not run: {type(ex).__name__}: {ex}"
    finally:
        WAITS_PATH = saved_wp
    check(24, "waiting time: first_seen cached, backfilled only from the record's own date markers", ok24, detail24,
          "STACK.md row 20 'OPEN (6 Sep 19:46)... SECURITY GATE ADDED 7 Sep 04:03'; eq.json 'asked': '2026-09-10'; "
          "sampler.json '[LISTEN, since 7 Sep, never boarded]'; eq.json next 'his sequencing order of 2 Sep 19:18'")

    # 25. The four free "may be settled" checks, each planted both ways; a check that cannot run says nothing.
    detail25, ok25 = "", False
    try:
        led_raw = ("# ANSWERS 2026-09-10\n\n| subject | when, how | his words |\n|---|---|---|\n"
                   "| reply from the Agents app | 21:30, about: [row 20] Pocket Fund: the go to build phases 0 and 1 "
                   "against his three rules | \"go\" |\n| reply | item id 7f3e9a1c2b | \"no\" |\n")
        board = ("# CROSS-LANE\n\n| # | since | what | from | affects | do |\n|---|---|---|---|---|---|\n"
                 "| 11 | 10 Sep | open row | a | b | c |\n| 14 | 10 Sep | listed twice | a | b | c |\n\n## CLOSED\n\n"
                 "| 12 | 10 Sep | closed row | a | b | c | CLOSED 19:4x: done |\n| 14 | 10 Sep | again | a | b | c | CLOSED |\n")
        eqp = os.path.join(LAB, "status/eq.json")
        ctx = {"now": now0, "ledgers": [("ANSWERS-test.md", led_raw, _norm(led_raw))], "cross": parse_cross_lane(board),
               "mtime": lambda p: {eqp: now0 - 3600}.get(p), "last_human": lambda lane: {"eq": now0 - 600}.get(lane)}
        cases25 = [
            ("answer by its text", {"id": "a1", "text": "[row 20] Pocket  Fund: the go to **build** phases 0 and 1 against his three rules, a long item"}, "your answer is in ANSWERS-test.md"),
            ("answer by its id", {"id": "7f3e9a1c2b", "text": "something else entirely, never answered in words"}, "your answer is in ANSWERS-test.md"),
            ("no answer", {"id": "a2", "text": "[row 21] a question nobody has answered yet at all"}, ""),
            ("file gone", {"id": "w1", "text": "move it", "world": "STALE"}, "a file it names is gone"),
            ("file there", {"id": "w2", "text": "move it", "world": "LIVE"}, ""),
            ("its cross-lane row closed", {"id": "c1", "text": "[CROSS-LANE row 12] Question: still needed?"}, "CROSS-LANE row 12 is closed"),
            ("its cross-lane row open", {"id": "c2", "text": "[CROSS-LANE 11] Question: still needed?"}, ""),
            ("row both open and closed", {"id": "c3", "text": "[CROSS-LANE #14] Question: still needed?"}, ""),
            ("a row only cited", {"id": "c4", "text": "Question: the backup (lab-common/CROSS-LANE.md row 12) is old; restore?"}, ""),
            ("he wrote after its record: the silence check is dropped (SPEC 11), no tag",
             {"id": "r1", "text": "q", "source": "status/eq.json:next", "owner_lane": "eq"}, ""),
            ("record rewritten after", {"id": "r2", "text": "q", "source": "status/eq.json:next", "owner_lane": "clip"}, ""),
            ("a listening folder", {"id": "r3", "text": "q", "source": "listening folders", "owner_lane": "eq"}, ""),
        ]
        bad25 = []
        for name, it, want in cases25:
            settle_fields(it, ctx)
            if it["settled_reason"] != want or it["may_be_settled"] != bool(want):
                bad25.append(f"{name} gave {it['settled_reason']!r}")
        broken = {"id": "x", "text": "q", "source": "status/eq.json:next", "owner_lane": "eq"}
        settle_fields(broken, {"now": now0})                  # no ledgers, no board, no readers: says nothing
        # the silence reason still exists, as a checker hint only
        hint = _settled_by_silence({"id": "r1", "text": "q", "source": "status/eq.json:next", "owner_lane": "eq"}, ctx)
        hint_ok = hint == f"you wrote to eq {_hhmm(now0 - 600, now0)}, its record is from {_hhmm(now0 - 3600, now0)}" \
            and _settled_by_silence in HINT_CHECKS and _settled_by_silence not in globals()["SETTLE_CHECKS"]
        # sabotage: the silence check back in SETTLE_CHECKS must make this control fail
        g25 = globals()
        saved25 = g25["SETTLE_CHECKS"]
        g25["SETTLE_CHECKS"] = saved25 + (_settled_by_silence,)
        try:
            it25 = {"id": "r1", "text": "q", "source": "status/eq.json:next", "owner_lane": "eq"}
            settle_fields(it25, ctx)
            caught25 = it25["may_be_settled"] is True
        finally:
            g25["SETTLE_CHECKS"] = saved25
        ok25 = not bad25 and broken["may_be_settled"] is False and hint_ok and caught25
        detail25 = (f"{len(cases25) - len(bad25)} of {len(cases25)} cases as expected"
                    + (f"; wrong: {'; '.join(bad25[:3])}" if bad25 else "")
                    + f"; with nothing readable the item stays open {broken['may_be_settled'] is False}"
                    + f"; silence reason kept as a checker hint only {hint_ok}"
                    + f"; sabotage (silence back in SETTLE_CHECKS) makes it fail {caught25}")
    except Exception as ex:
        detail25 = f"could not run: {type(ex).__name__}: {ex}"
    check(25, "may be settled: only the strong checks (answer ledger, file gone, its CROSS-LANE row closed); silence dropped",
          ok25, detail25, "CROSS-LANE.md 10 Sep: rows under '## CLOSED' carry a last cell 'CLOSED 19:4x: ...'; "
          "sampler item d7dddd6445 cites '(lab-common/CROSS-LANE.md row 5)' as evidence")

    # 26. Ownership, and conservation: every item lands on exactly one row or on "unowned".
    detail26, ok26 = "", False
    try:
        roster = {"s-coord": {"lane": "coordinator", "status_file": None},
                  "s-old": {"lane": "sampler", "status_file": "sampler.json"},
                  "s-samp": {"lane": "sampler", "status_file": "sampler.json"},
                  "s-eq": {"lane": "eq", "status_file": "eq.json"},
                  "s-lvl": {"lane": "level", "status_file": "level.json"}}
        live = {"s-coord": 1, "s-samp": 2, "s-eq": 3}                 # s-old and s-lvl are not running
        lanes = ["stack", "when-home", "listens", "sampler", "sampler", "eq", "level", "ghost"]
        w26 = waiting_from_manifest({"total": len(lanes), "counts": {"decision": len(lanes)}, "sha": "t26",
                                     "items": [{"id": f"i{k}", "lane": ln, "bucket": "decision", "text": f"item {k}",
                                                "source": "x"} for k, ln in enumerate(lanes)]})
        fsd = {f"i{k}": now0 - 3600 * (k + 1) for k in range(len(lanes))}
        enrich(w26, now0, {"now": now0, "roster": roster, "live": live, "stack_states": {}, "ledgers": [], "cross": {},
                           "mtime": lambda p: None, "last_human": lambda lane: None}, fsd)
        rows26 = [{"session_id": sid} for sid in ("s-coord", "s-samp", "s-eq", "s-other")] + [{"session_id": None}]
        attach_waits(rows26, w26)
        got = [(r["session_id"], r.get("decisions_waiting"), r.get("total_wait_seconds")) for r in rows26]
        want = [("s-coord", 3, 3600 * (1 + 2 + 3)), ("s-samp", 2, 3600 * (4 + 5)), ("s-eq", 1, 3600 * 6),
                ("s-other", 0, 0), (None, None, None)]
        n_sum = sum(r.get("decisions_waiting") or 0 for r in rows26) + w26["unowned"]
        t_sum = sum(r.get("total_wait_seconds") or 0 for r in rows26) + w26["unowned_wait_seconds"]
        failed = [{"session_id": "s-coord"}]
        attach_waits(failed, {"ok": False, "items": []})
        ok26 = (got == want and n_sum == w26["total"] and t_sum == sum(i["waited_seconds"] for i in w26["items"])
                and w26["unowned"] == 2 and failed[0].get("decisions_waiting") is None)
        detail26 = (f"rows {got}; rows plus unowned: {n_sum} items of {w26['total']}, {t_sum} s of "
                    f"{sum(i['waited_seconds'] for i in w26['items'])} s; unowned {w26['unowned']} (expected 2, level and ghost); "
                    f"a failed list leaves the row at {failed[0].get('decisions_waiting')} ('?')")
    except Exception as ex:
        detail26 = f"could not run: {type(ex).__name__}: {ex}"
    check(26, "decisions waiting per conversation: stack, when-home, listens to WORKFLOW; the live one of two sampler "
          "sessions; the sums add up to the manifest", ok26, detail26,
          "roster.json 10 Sep: lane sampler has 79afe78e and e5508b4b ('did not come back')")

    # 27. Alarms print FIRST in the CLI text and lead the JSON.
    detail27, ok27 = "", False
    try:
        led = os.path.join(sdir, "ALARMS.jsonl")
        am = _alarm_module()
        am.append({"id": "A0910-220000-aaaa", "event": "raised", "t": "2026-09-10T21:00:00-0400", "from": "Storage",
                   "why": "Free disk will reach the floor within the hour and two long runs are registered."}, led)
        am.append({"id": "A0910-210000-bbbb", "event": "raised", "t": "2026-09-10T20:00:00-0400", "from": "Clip",
                   "why": "A closed alarm that must not show on the list at all, it was resolved."}, led)
        am.append({"id": "A0910-210000-bbbb", "event": "resolved", "t": "2026-09-10T20:30:00-0400", "from": "Clip",
                   "note": "done"}, led)
        am.append({"id": "A0910-220000-aaaa", "event": "ack", "t": "2026-09-10T21:05:00-0400", "from": "Dreiling_EQ",
                   "note": "pausing"}, led)
        al = {"ok": True, "alarms": alarms(led), "message": ""}
        wq = waiting_from_manifest({"total": 0, "counts": {}, "sha": "x", "items": []})
        txt = render_text([], wq, al)
        lines = txt.split("\n")
        none_first = render_text([], wq, {"ok": True, "alarms": [], "message": ""}).split("\n")[0]
        err_first = render_text([], wq, {"ok": False, "alarms": None, "message": "the alarm list could not be read (x)"}).split("\n")[0]
        first_key = next(iter(cli_payload(al, [], {}, wq)))
        ok27 = (lines[0] == "ALARMS: 1 open, oldest first" and lines[1].startswith("  ALARM from Storage: Free disk")
                and "answered by Dreiling_EQ" in lines[2] and "bbbb" not in txt
                and txt.index("ALARM from") < txt.index("AGENTS,") and none_first == "ALARMS: none open."
                and err_first.startswith("ALARMS: the alarm list could not be read") and first_key == "alarms")
        detail27 = f"first lines {lines[:3]}; no alarms -> {none_first!r}; unreadable -> {err_first!r}; JSON leads with {first_key!r}"
    except Exception as ex:
        detail27 = f"could not run: {type(ex).__name__}: {ex}"
    check(27, "open alarms come first in the CLI text and the JSON; a resolved alarm is not shown", ok27, detail27,
          "SPEC section 5: 'The engine returns open alarms FIRST in its CLI output'")

    # 28. Storage: the estimate after running work, the trend, the colour, Time Machine.
    global STORAGE_PATH
    saved_sp, saved_sizes = STORAGE_PATH, dict(_STORE_MEM["sizes"])
    detail28, ok28 = "", False
    try:
        STORAGE_PATH = os.path.join(sdir, "storage.json")
        _STORE_MEM["sizes"].clear()
        sizes = {"grow": [1 * GIB, 3 * GIB], "shrink": [5 * GIB, 1 * GIB]}
        call = {"n": 0}

        def sizer(p):
            name = os.path.basename(p)
            if name == "locked":
                raise PermissionError(1, "Operation not permitted")
            return sizes[name][call["n"]]
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now0 - 1800))
        runs = [{"name": "grows 2 GiB", "lane": "a", "pid": -1, "scratch": "/x/grow", "disk_gb": 5.0, "hours": 2.0,
                 "started": started, "state": "running"},
                {"name": "unreadable", "lane": "b", "pid": -1, "scratch": "/x/locked", "disk_gb": 4.0, "hours": 1.0,
                 "started": started, "state": "running"},
                {"name": "shrinks", "lane": "c", "pid": -1, "scratch": "/x/shrink", "disk_gb": 2.0, "hours": 1.0,
                 "started": started, "state": "running"},
                {"name": "finished", "lane": "d", "pid": -1, "scratch": "/x/grow", "disk_gb": 100.0, "state": "finished"},
                {"name": "declares nothing", "lane": "e", "pid": -1, "scratch": "", "state": "running"}]
        tm0 = {"running": False, "phase": "", "percent": None, "note": ""}
        a = storage(now=now0, free=50.0, runs=runs, sizer=sizer, tm=tm0)
        call["n"] = 1
        b = storage(now=now0 + SCRATCH_EVERY + 10, free=50.0, runs=runs, sizer=sizer, tm=tm0)
        c = storage(now=now0 + SCRATCH_EVERY + 20, free=50.0, runs=runs, sizer=sizer, tm=tm0)   # 10 s later: no new sample
        with open(STORAGE_PATH) as fh:
            n_samples = len(json.load(fh)["samples"])
        byname = {r["name"]: r for r in b["runs"]}
        est_ok = (a["after_running_gib"] == 39.0 and b["after_running_gib"] == 41.0
                  and byname["grows 2 GiB"]["used_gib"] == 2.0 and byname["shrinks"]["used_gib"] == 0.0
                  and byname["unreadable"]["remaining_gib"] == 4.0 and byname["unreadable"]["used_gib"] is None
                  and byname["declares nothing"]["remaining_gib"] is None and "finished" not in byname
                  and abs(byname["grows 2 GiB"]["hours_left"] - 1.5 + (SCRATCH_EVERY + 10) / 3600) < 0.01
                  and "about 41.0 GiB, an estimate" in b["text"] and n_samples == 2)
        none_txt = storage(now=now0, free=50.0, runs=[runs[4]], sizer=sizer, tm=tm0, persist=False)["text"]
        # trend: 12 samples, 5 minutes apart, falling exactly 0.3 GiB an hour; one old outlier outside the hour
        pts = [(now0 - 55 * 60 + k * 300, 80.0 - 0.3 * (k * 300) / 3600) for k in range(12)] + [(now0 - 7000, 500.0)]
        s12, n12 = trend(pts, now0)
        s9, n9 = trend(pts[:9], now0 - 15 * 60 + 1)
        flat = [(now0 - 3000 + k * 300, 70.0 + 0.04 * (k * 300) / 3600) for k in range(10)]
        tr_ok = (s12 is not None and abs(s12 + 0.3) < 1e-9 and n12 == 12 and trend_text(s12) == "falling 0.3 GiB an hour"
                 and s9 is None and trend_text(trend(flat, now0)[0]) == "steady")
        lv = [disk_level(x) for x in (29.9, 30.0, 40.0, 40.1)]
        tmr = parse_tmutil('Backup session status:\n{\n    BackupPhase = Copying;\n    ClientID = "com.apple.backupd";\n'
                           '    Progress =     {\n        Percent = "0.8937184679319641";\n    };\n    Running = 1;\n}')
        tmo = parse_tmutil("Backup session status:\n{\n    ClientID = \"com.apple.backupd\";\n    Running = 0;\n}")
        tm_ok = (tmr["running"], tmr["phase"], tmr["percent"]) == (True, "Copying", 89.4) and (tmo["running"], tmo["phase"]) == (False, "")
        ok28 = est_ok and "no running work declares disk" in none_txt and tr_ok and lv == ["red", "orange", "orange", "normal"] and tm_ok
        detail28 = (f"after running work {a['after_running_gib']} then {b['after_running_gib']} GiB (expected 39.0 then 41.0: "
                    f"growth 2 counted, a shrink counts 0, an unreadable scratch counts its full 4, a finished run and a "
                    f"run declaring nothing count 0); samples written {n_samples} (expected 2); trend {s12 and round(s12, 6)} "
                    f"GiB an hour from {n12} samples (expected -0.3 from 12), 9 samples give {s9}; colours {lv}; "
                    f"Time Machine {tmr['running']} {tmr['phase']} {tmr['percent']}, then {tmo['running']}")
    except Exception as ex:
        detail28 = f"could not run: {type(ex).__name__}: {ex}"
    finally:
        STORAGE_PATH = saved_sp
        _STORE_MEM["sizes"].clear(); _STORE_MEM["sizes"].update(saved_sizes)
    check(28, "storage: estimate after running work, never negative growth, trend only from 10 samples, colours, "
          "Time Machine", ok28, detail28, "runs.json 10 Sep (disk_gb, scratch, hours, started, state); tmutil status "
          "10 Sep 21:5x 'BackupPhase = Copying; Percent = \"0.8937...\"; Running = 1;'")

    # 29. Free space and scratch size against the system's own tools. df reads the same kernel call, so
    # this checks this engine's arithmetic and volume choice, not the kernel's number.
    detail29, ok29 = "", False
    try:
        mine = free_gib()
        dfo = subprocess.run(["df", "-k", data_volume()], capture_output=True, text=True, timeout=10).stdout.split("\n")[1].split()
        theirs = int(dfo[3]) * 1024 / GIB
        dz = os.path.join(sdir, "sized")
        os.makedirs(os.path.join(dz, "sub"))
        for k, n in enumerate((100_000, 250_000, 4096)):
            with open(os.path.join(dz, "sub" if k else "", f"f{k}"), "wb") as fh:
                fh.write(b"\1" * n)
        got_b = dir_size(dz)
        du_b = int(subprocess.run(["du", "-sk", dz], capture_output=True, text=True, timeout=10).stdout.split()[0]) * 1024
        lock = os.path.join(dz, "sub", "locked")
        os.makedirs(lock)
        os.chmod(lock, 0)
        try:
            dir_size(dz)
            refused = False
        except OSError:
            refused = True
        finally:
            os.chmod(lock, 0o755)
        ok29 = abs(mine - theirs) < 0.05 and abs(got_b - du_b) <= 16384 and got_b >= 354_096 and refused
        detail29 = (f"statvfs {mine:.3f} GiB, df {theirs:.3f} GiB; planted folder {got_b} bytes, du {du_b} bytes; "
                    f"an unreadable subfolder gives no reading {refused}")
    except Exception as ex:
        detail29 = f"could not run: {type(ex).__name__}: {ex}"
    check(29, "free space and scratch size agree with df and du; an unreadable folder is no reading, never a partial size",
          ok29, detail29)
    # 30. The new numbers fail loudly: a headline that cannot be measured says so in the row's note, and
    # the table's decision counts drop to "?" the moment the waiting list fails or grows old.
    saved_mf, saved_q, saved_mod, saved_last = message_fields, QUEUE_PY, dict(_QUEUE), dict(_LAST_WAITING)
    detail30, ok30 = "", False
    try:
        def boom(md_):
            raise RuntimeError("planted")
        globals()["message_fields"] = boom
        row30, notes30 = _row("t", "ttys000", 1), []
        _message_into_row(row30, "Done.", None, "transcript", False, notes30)
        globals()["message_fields"] = saved_mf
        good = waiting_from_manifest({"total": 1, "counts": {"decision": 1}, "sha": "g", "items": [
            {"id": "g1", "lane": "eq", "bucket": "decision", "text": "t", "source": "x"}]})
        enrich(good, now0, {"now": now0, "roster": {"s-eq": {"lane": "eq"}}, "live": {"s-eq": 1}, "stack_states": {},
                            "ledgers": [], "cross": {}, "mtime": lambda p: None, "last_human": lambda l: None}, {"g1": now0})
        _LAST_WAITING.update(w=good, t=time.time())
        before = attach_waits([{"session_id": "s-eq"}], _recent_waiting())[0].get("decisions_waiting")
        QUEUE_PY = os.path.join(sdir, "no-such-queue.py")
        _QUEUE.update(mod=None, mtime=None)
        failed = waiting()
        after = attach_waits([{"session_id": "s-eq"}], _recent_waiting())[0].get("decisions_waiting")
        _LAST_WAITING.update(w=good, t=time.time() - WAITING_MEMO_MAX - 1)
        aged = attach_waits([{"session_id": "s-eq"}], _recent_waiting())[0].get("decisions_waiting")
        ok30 = (row30["headline"] is None and any("headline could not be measured (RuntimeError: planted)" in n for n in notes30)
                and row30["full_text"] == "Done." and before == 1 and not failed["ok"] and after is None and aged is None)
        detail30 = (f"note {notes30}; counts with a good list {before}, after the list failed {after}, "
                    f"with a list {WAITING_MEMO_MAX + 1} s old {aged} (expected 1, None, None)")
    except Exception as ex:
        detail30 = f"could not run: {type(ex).__name__}: {ex}"
    finally:
        globals()["message_fields"] = saved_mf
        QUEUE_PY = saved_q
        _QUEUE.clear(); _QUEUE.update(saved_mod)
        _LAST_WAITING.clear(); _LAST_WAITING.update(saved_last)
    check(30, "a headline that cannot be measured says so; the table's counts never outlive a failed or old list",
          ok30, detail30)

    # 31. The clock never takes seconds back. Registry busy after a turn ended (background work running),
    # then a peer's prompt lands; then a tool call that runs 200 s. At every second the shown value is
    # live_seconds of the row as the table would build it; it must never fall below the largest value
    # shown before, and after each new entry it must equal a cold recount of the transcript.
    try:
        t31 = now0 - 4000
        T = _T(t31)
        T.prompt(0, "go", origin="human")
        T.say(100, "Done.", stop="end_turn")
        marks = [(100, len(T.lines))]
        T.prompt(1200, "Another Claude session sent a message")      # 1100 s later: a gap that never counts
        marks.append((1200, len(T.lines)))
        T.call(1210, "Bash", {"command": "sleep 200"}, "toolu_c31")
        marks.append((1210, len(T.lines)))
        T.result(1410, "toolu_c31", "done")
        marks.append((1410, len(T.lines)))

        def _row31(n):
            s = _run(T.lines[:n])
            return {"seconds_working": int(s["seconds"]), "last_entry_ts": s["prev_ts"],
                    "working": working_state("busy", s), "ticking": ticking_state(s)}, int(s["seconds"])
        shown_max, fell, recount_bad = 0, [], []
        for k, (dt, n) in enumerate(marks):
            row31, cold = _row31(n)
            if live_seconds(row31, t31 + dt) != cold:
                recount_bad.append(f"at +{dt} s shows {live_seconds(row31, t31 + dt)}, cold recount {cold}")
            end = marks[k + 1][0] if k + 1 < len(marks) else dt + 60
            for sec in range(dt, end + 1):
                v = live_seconds(row31, t31 + sec)
                if v < shown_max:
                    fell.append(f"+{sec} s: {v} after {shown_max}")
                    break
                shown_max = max(shown_max, v)
        busy_end, _c = _row31(marks[0][1])
        frozen = live_seconds(busy_end, t31 + 100) == live_seconds(busy_end, t31 + 1100)
        ticked = live_seconds(_row31(marks[2][1])[0], t31 + 1310) - live_seconds(_row31(marks[2][1])[0], t31 + 1210)
        ok31 = not fell and not recount_bad and busy_end["working"] is True and frozen and ticked == 100
        detail31 = (f"working while busy after end of turn {busy_end['working']}, clock frozen there {frozen}; "
                    f"ticks during a tool call {ticked} s in 100 s; never fell {not fell}"
                    + (f" ({fell[0]})" if fell else "") + f"; equals the cold recount at each entry {not recount_bad}"
                    + (f" ({recount_bad[0]})" if recount_bad else ""))
    except Exception as ex:
        ok31, detail31 = False, f"could not run: {type(ex).__name__}: {ex}"
    check(31, "Time spent never goes down: it ticks only mid-turn, so no shown second is taken back", ok31, detail31,
          "checker 10 Sep 23:21: WORKFLOW 14 h 10 m 26 s ticking while its registry read busy after an end_turn "
          "at 23:04:04, then 13 h 55 m 45 s at 23:35 once 'Another Claude session sent a message' landed")
    # 32. SPEC section 11, the headline rule: a headline needs no end punctuation (at most 50 visible
    # characters, not code); the summary must still end a statement. Sabotage: the old rule (a headline
    # must end a statement) planted back must make this control fail.
    def cases32():
        got, bad = {}, []
        planted = {
            "Waiting on you, no end punctuation": ("**Waiting on you:** approve the install\nThe install is ready.",
                                                  dict(h_ok=True, wo=True, s_text="The install is ready.", s_ok=True)),
            "a plain headline with no period": ("Clip 2.0 shipped to the library\nEvery preset loads and nulls.",
                                               dict(h_ok=True, s_ok=True, s_from="second line")),
            "summary without an end is not ok": ("Short headline\nThe summary trails off without an end",
                                                dict(h_ok=True, s_ok=False, s_complete=False)),
            "51 visible, no period, still over": ("B" * 51 + "\nNext.", dict(h_ok=False, h_over=True)),
            "code first line is never a headline": ("```\nprint(1)\n```\nDone.", dict(h_ok=False)),
        }
        for name, (md_, want) in planted.items():
            h, sm, wo = message_fields(md_)
            have = dict(h_ok=h["ok"], h_over=h["over"], s_text=sm["text"], s_ok=sm["ok"], s_complete=sm["complete"],
                        s_from=sm["from"], wo=wo)
            got[name] = {k: have[k] for k in want}
            if got[name] != want:
                bad.append(name)
        return planted, got, bad
    try:
        planted32, got32, bad32 = cases32()
        tag32 = _line_tags(message_fields("Waiting on you: approve it")[0], HEADLINE_MAX)
        saved32 = globals()["HEADLINE_NEEDS_END"]
        globals()["HEADLINE_NEEDS_END"] = True
        try:
            _p, _g, sab32 = cases32()
        finally:
            globals()["HEADLINE_NEEDS_END"] = saved32
        ok32 = not bad32 and tag32 == "" and bool(sab32)
        detail32 = (f"{len(planted32) - len(bad32)} of {len(planted32)} cases as expected"
                    + (f"; first wrong: {bad32[0]} gave {got32[bad32[0]]}" if bad32 else "")
                    + f"; the CLI tags a headline with no period {tag32!r} (want none)"
                    + f"; sabotage (headline must end a statement) makes {len(sab32)} case(s) fail")
    except Exception as ex:
        ok32, detail32 = False, f"could not run: {type(ex).__name__}: {ex}"
    check(32, "headline rule (SPEC 11): no end punctuation needed within 50; the summary must end a statement", ok32,
          detail32, "SPEC section 11 'A news headline has no end punctuation... \"Waiting on you: X\" is a valid headline'")

    # 33. SPEC section 11, asks without a reason: queue.py's unjustified WAITING ON lines pass through as
    # "unjustified", each with its lane and a stable key, never counted in total or counts. Sabotage: a
    # pass-through that drops them must make this control fail.
    m33 = {"total": 1, "counts": {"decision": 1}, "sha": "s33",
           "items": [{"id": "k1", "text": "WAITING ON MASON: pick A or B, because only he can.", "lane": "eq",
                      "bucket": "decision", "source": "status/eq.json:next", "world": "LIVE"}],
           "unjustified": [{"lane": "eq", "field": "next", "text": "WAITING ON MASON: say go \u2014 now", "justified": False},
                           {"lane": "clip", "field": "blocked", "text": "WAITING ON MASON: pick the knob", "justified": False},
                           {"lane": "clip", "field": "blocked", "text": "WAITING ON MASON: pick the knob", "justified": False},
                           "not a dict", {"lane": "x", "text": "   "}]}

    def run33():
        w = waiting_from_manifest(m33)
        u = w.get("unjustified") or []
        return w, u
    try:
        w33, u33 = run33()
        again = waiting_from_manifest(m33).get("unjustified") or []
        ok_shape = ([(x["lane"], x["text"]) for x in u33] == [("eq", "WAITING ON MASON: say go, now"),
                                                               ("clip", "WAITING ON MASON: pick the knob")]
                    and all(len(x["key"]) == 10 for x in u33) and [x["key"] for x in again] == [x["key"] for x in u33]
                    and w33.get("unjustified_total") == 2)
        not_counted = w33["total"] == 1 and w33["counts"] == {"decision": 1} and len(w33["items"]) == 1
        txt33 = render_text([], dict(w33, ok=True))
        cli33 = "Asked of you without saying why (2), not counted above" in txt33 and "lane clip: WAITING ON MASON: pick the knob" in txt33
        saved33 = globals()["unjustified_from_manifest"]
        globals()["unjustified_from_manifest"] = lambda m: []
        try:
            _w, sab33 = run33()
        finally:
            globals()["unjustified_from_manifest"] = saved33
        ok33 = ok_shape and not_counted and cli33 and sab33 == []
        detail33 = (f"2 kept of 5 planted (a duplicate, a non-dict and a blank dropped) {ok_shape}; never counted "
                    f"(total 1, counts unchanged) {not_counted}; the CLI lists them last with their lanes {cli33}; "
                    f"sabotage (pass-through dropped) makes it fail {sab33 == []}")
    except Exception as ex:
        ok33, detail33 = False, f"could not run: {type(ex).__name__}: {ex}"
    check(33, "asks without a reason (SPEC 11): passed through with their lanes, never counted", ok33, detail33,
          "queue.py build(): 'unjustified' lines, WAITING ON MASON without 'because' (fence 50)")

    _sh.rmtree(sdir, ignore_errors=True)

    try:
        os.rmdir(os.path.join(CACHE_DIR, "selftest"))   # the planted worlds' parent, empty by now
    except OSError:
        pass
    failed = results.count(False)
    print()
    print(f"{len(results) - failed} of {len(results)} controls pass" + ("" if not failed else f", {failed} FAIL"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
