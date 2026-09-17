#!/usr/bin/env python3
"""decisions.py: "decisions" = the live grouped choice list, in his fixed shape, printed by a script.

Mason, 15 Sep 2026: "When i say decisions... i probably want you to run a script that gives me an
up-to-date output like this:" (the shape is tests/decisions-sample-2026-09-15.md). And SPEC.md item 16,
ONE ANSWER, EVERY ASKER: "If i have 3 agents asking the same question, then i should just have to give
one answer one time".

READ-ONLY. This script reads the console through monitor_data.waiting() and monitor_data.conversations()
and writes nothing anywhere (monitor_data keeps its own caches; nothing here touches a status file, a
ledger, the roster or STACK.md). Deterministic by default: no model call. --polish is opt-in.

Usage:
    python3 decisions.py               the list, plain text
    python3 decisions.py --ids         each line also carries the console ids it was built from
    python3 decisions.py --json        the grouped structure
    python3 decisions.py --polish      the printed lines rewritten by the same headless Claude route
                                       monitor_actions uses (Haiku, no tools); OFF by default, never in
                                       the controls; on any failure the deterministic lines print
    python3 decisions.py --selftest    the planted controls (fixtures under tests/decisions/, no live
                                       files); exit 1 if any fails; prints the predictions at the end
    python3 decisions.py --live-check  tests those predictions on live data, PASS/FAIL with numbers

WHAT IT DOES, in order (the numbers in the report say which step did what):
  1. INPUT: monitor_data.waiting() items, exactly as the console shows them.
  2. DROP: an item the engine marks may_be_settled WITH a reason goes to "Closing now, not choices",
     printed with its reason, never silently. Paused lanes are already kept off by the engine
     (lab-common/paused_lanes.json); one line says which lanes and how many asks that holds.
  3. FOLD: every listening-folder item ("N files to hear in <folder>") and a when-home item that points
     at the same pile fold into ONE choice naming the total folders and files and the two smallest folders.
  4. GROUP: the same question asked from several places is ONE choice:
     (a) a DECLARED link wins: a "same_as" field on a decisions_for_mason ask (queue.py renders it into the
         item text as "Same as: ...", which is how it reaches this script without reading status files),
         carrying another ask's console id, a STACK row ("row 24", "STACK 24"), a when-home number, or a
         short group key shared by every ask in the group; or the lab's own convention of naming the row
         that holds an ask ("[STACK 23]", "WHEN HOME 2"), which decisions_check.py already requires.
     (b) otherwise a TEXT rule: see similarity() and the JOIN_* constants for the threshold and why.
     A group's members are joined transitively (A with B and B with C is one group).
  4b. PROJECT FOLD (from the sample's shape, line 33 "Chapel bid ... seven answers"): asks of one lane
     that open with the same project label ("Chapel: ...", "Storefront: ...") are one sitting and print as
     one numbered line listing each ask. Labelled "K console items, one project", never "one question".
  5. SECTIONS by lane (SECTIONS below): Plugins; At the Mac, when home; Email and business; Other.
  6. EACH LINE: "N. <Lane label>: <ask>. <Recommendation>. <tags>": the ask is the item's ask sentence with
     lead tags ([STACK 23], [GO/NO-GO]) and form labels (Question:, WAITING ON MASON:) removed and any
     "because" clause dropped, cut at a word boundary at ASK_MAX characters; the recommendation is the
     first sentence saying "recommend" (else omitted); tags from bucket/needs/text: At the Mac, Listen,
     Send, Optional; a group adds "K console items are this one question".
  7. HEADER: "Waiting on you: N choices, grouped from M console items", then a summary under 200
     characters, then the closing list, the sections, the paused-lanes line, and "One gap I see" only when
     computable (a conversation whose headline says "Waiting on you" while it has 0 items on the list).

No em or en dash is ever printed: every one in a source text becomes a comma (dash_free()).
"""
import argparse
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "tests", "decisions")
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ---------------------------------------------------------------------------------------------
# The lane map. Edit here. A lane not named in any section prints under "Other".
# ---------------------------------------------------------------------------------------------
SECTIONS = [
    ("Plugins", ["comp", "eq", "clip", "clip2", "sampler", "level", "limit", "autotune", "midi",
                 "protools", "maximizer", "stack", "coordinator", "listens"]),
    ("At the Mac, when home", ["when-home"]),
    ("Email and business", ["email", "di", "finance", "travelfund"]),
    ("Other", None),
]
LANE_LABEL = {
    "comp": "Comp", "eq": "EQ", "clip": "Clip", "clip2": "Clip", "sampler": "Sampler", "level": "Leveller",
    "limit": "Oracle", "autotune": "Autotune", "midi": "MIDI", "protools": "Pro Tools", "maximizer": "Maximizer",
    "email": "Email", "di": "Day job", "finance": "Finance", "travelfund": "Finance", "coordinator": "Coordinator",
    "stack": "Coordinator", "when-home": "Coordinator", "listens": "Listening pile",
    "presets": "Presets", "storage": "Storage", "room": "Room correction",
}
# A STACK row or a when-home item carries lane "stack"/"when-home"; its label is its SUBJECT, read from the
# first of these that appears in its text (earliest position wins). Nothing matched: Coordinator.
STACK_SUBJECTS = [
    (r"\btask priority\b|\bqos\b", "Task priority"),
    (r"\bcomp(?:'s)?\b|\bcompressor\b", "Comp"),
    (r"\beq(?:'s)?\b|\bequali[sz]er\b", "EQ"),
    (r"\bclip(?:'s)?\b|\bclipper\b|\bhq brick", "Clip"),
    (r"\bsampler(?:'s)?\b|\bzone editor\b|\bdaw\b|\bdrum kits\b", "Sampler"),
    (r"\bleveller\b|\blevel lane\b", "Leveller"),
    (r"\boracle\b|\blimiter\b|\blimit lane\b", "Oracle"),
    (r"\bautotune\b", "Autotune"),
    (r"\bmidi\b", "MIDI"),
    (r"\bpro tools\b|\baax\b", "Pro Tools"),
    (r"\bmaximi[sz]er\b", "Maximizer"),
    (r"\bemail\b|\bmailbox\b", "Email"),
    (r"\bchapel\b|\bstorefront\b|\bday job\b", "Day job"),
]
PAUSED_LABEL = {"room": "Room correction", "travelfund": "Finance (Travel Fund)", "storage": "Storage",
                "finance": "Finance"}
PROJECT_FOLD = True          # step 4b; set False to print every project ask on its own line

ASK_MAX = 170                # the one-line ask is cut at a word boundary here (step 6)
REC_MAX = 120                # and the recommendation here
SUB_ASK_MAX = 90             # each ask inside a project fold
HEADLINE_MAX = 60            # line 1 stays under this
SUMMARY_MAX = 200            # line 2 under this

# ---------------------------------------------------------------------------------------------
# The text rule (step 4b). Two asks are the same question when they share enough DISTINCTIVE terms.
#
# Terms: word 1-grams plus 2-grams of the item text after lead tags, file paths, dates, times, commit
# hashes, the lanes' form words (Question:, Now:, Consequences:, Reversible:, Recommendation:, Evidence:,
# Because:, Kind:) and English stopwords are out; numbers are kept (Threshold -40 and Ratio 10 are what
# make the Live Compressor ask itself).
#
# Score = the larger of two Jaccard-style overlaps:
#   OV   shared terms over the SMALLER term set (the overlap coefficient). Plain Jaccard divides by the
#        union, so a one-line ask against a 900-character brief of the same question can never pass:
#        Comp's Live Compressor line (50 terms) against when-home 9 (132 terms) is Jaccard 0.15 but
#        OV 0.48. Dividing by the smaller set asks "how much of the shorter one is in the longer one".
#   CONT how much of one item's ASK SENTENCE (its question, not its brief) appears anywhere in the other
#        item's text, either direction, counted only when the ask has ASK_MIN_TERMS terms. This is what
#        joins the sampler's "private GitHub copy" ask to STACK row 25, a brief about four repos: the
#        question is a fifth of the row's words but nearly half of the ask's.
# A pair joins when score >= JOIN_SCORE AND it shares at least JOIN_MIN_SHARED terms of which at least
# JOIN_MIN_BIGRAMS are 2-grams (a shared word PAIR is the wording signal; single words like "name",
# "knob" or "plan" join nothing on their own).
#
# Where the numbers sit on the 15 Sep 2026 console (67 items, 15:40; measured by --live-check and the
# tuning harness that printed every pair):
#   true pairs (score, shared terms, shared 2-grams)
#       row 23 / sampler's [STACK 23] brief          0.91, 84, 41
#       row 23 / sampler audit find 1                0.59, 28, 10
#       sampler [STACK 23] / sampler audit find 1    0.43, 40, 16
#       row 24 / EQ audit item 2 of 2                0.39, 22, 7
#       sampler private GitHub copy / row 25         0.38 (CONT; OV only 0.12), 13, 2
#       Comp Live Compressor / when-home 9           0.82, 24, 10
#   false pairs that score ABOVE 0.30 and are refused by the count floors
#       Leveller output knob / sampler half-waves    0.50 but 9 shared, 1 2-gram   (a short ask, 4 words in common)
#       when-home 9 / Comp update check              0.44 but 5 shared, 0 2-grams
#       Email GitHub two-factor / sampler GitHub copy 0.33 but 5 shared, 2 2-grams ("github account", "account prod")
#   the highest false pair that clears BOTH count floors scores 0.17 (row 25 against the sampler's
#   zone-editor brief, two long texts with 9 words in common), so JOIN_SCORE 0.30 has a margin of 0.13
#   above it and the weakest true pair (0.38) sits 0.08 above JOIN_SCORE. JOIN_MIN_SHARED 8 refuses the two-factor pair:
#   a five-term coincidence is not a shared question. The EQ "V2 plan" ask shares two common words with
#   its two partners (score 0.07) and NO rule on words can join it honestly; that is what same_as is for.
# ---------------------------------------------------------------------------------------------
JOIN_SCORE = 0.30
JOIN_MIN_SHARED = 8
JOIN_MIN_BIGRAMS = 2
ASK_MIN_TERMS = 8

STOPWORDS = set("""
a an the and or but nor so yet of to in on at by for with from as into onto over under about than then that
this these those there here it its is are was were be been being am do does did done doing have has had
having will would shall should can could may might must not no yes if else when whenever where whether
while because since until unless which who whom whose what why how all any each every either neither both
few more most other some such only own same very just now new old first second next last also ever never
always again further once he him his she her they them their theirs we us our ours you your yours i me my
mine himself herself itself themselves yourself myself ourselves off out up down above below between through
during before after against along around among across behind beyond within without via per say says said
saying tell told ask asks asked give gives gave get gets got go goes went come comes came make makes made
take takes took keep keeps kept let lets put puts set sets see sees saw know knows knew think thinks thought
want wants wanted need needs needed use uses used run runs ran read reads still already today tonight day
days week weeks hour hours minute minutes seconds time times jan feb mar apr may jun jul aug sep sept oct
nov dec january february march april june july august september october november december lane lanes mason
coordinator kind decide send because option options recommendation recommend recommends recommended
consequence consequences reversible evidence true question answer answers none nothing something anything
everything one two three four five six seven eight nine ten item items console list waiting wait waits
open since boarded words word never ever also even much many long short well way thing things
""".split())

_LEAD_TAGS = re.compile(r"^(?:\s*(?:\[[^\]]{0,160}\]|\d+[.)]|[-*])\s*)+")
_FORM_LABELS = re.compile(
    r"\b(?:what is true now|true now|now|consequences?|reversible|recommendation|evidence|options?|because|"
    r"kind|asked|question|disposition|same as)\s*:", re.I)
_WAITING = re.compile(r"\bWAITING ON MASON(?:'S HANDS| for one decision)?\s*[:,]?\s*", re.I)
_DASHES = re.compile(r"\s*[‒–—―]\s*")
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9(\[\"'])|\n+")
_HEX = re.compile(r"^[0-9a-f]{7,40}$")


# ---------------------------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------------------------

def dash_free(s):
    """No em or en dash is ever printed. Each becomes a comma, the engine's own rule for descriptions."""
    s = _DASHES.sub(", ", s or "")
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r",\s*([.?!;:])", r"\1", s)
    return s


def strip_lead(text):
    return _LEAD_TAGS.sub("", text or "", count=1).strip()


def sentences(text):
    parts = [p.strip() for p in _SENTENCE_END.split(strip_lead(text)) if p and p.strip()]
    return parts


def _drop_because(s):
    """A ", because ..." clause goes, to the end of the sentence; when a colon follows inside the clause
    (Comp's update check: "because it decides ...: list only (recommended) or plugin and version sent")
    only the clause before the colon goes, so the choice itself survives."""
    m = re.search(r"\s*[,;]?\s*\bbecause\b", s, re.I)
    if not m:
        return s
    head, tail = s[:m.start()], s[m.end():]
    c = tail.find(":")
    if c >= 0 and len(tail) - c > 8:
        return (head + tail[c:]).strip()
    return head.strip()


_NAMES = {"m-leveller": "M-Leveller", "leveller": "Leveller", "maximizer": "Maximizer", "maschine": "Maschine",
          "mason": "Mason", "eq": "EQ", "midi": "MIDI", "aax": "AAX", "hq": "HQ", "daw": "DAW", "led": "LED",
          "lcd": "LCD", "ssd": "SSD", "usb": "USB", "github": "GitHub", "iphone": "iPhone", "mac": "Mac",
          "qos": "QoS", "pro tools": "Pro Tools", "vst3": "VST3", "au": "AU", "root": "ROOT", "tb": "TB",
          "gb": "GB", "mb": "MB", "png": "PNG", "wav": "WAV", "cts": "CTS", "avixa": "AVIXA", "po": "PO",
          "live": "Live", "oracle": "Oracle", "clip": "Clip", "comp": "Comp"}
_SHOUT = re.compile(r"\b[A-Z][A-Z'\-]+(?:[,;:]?\s+[A-Z][A-Z'\-]+){3,}\b")


def _sentence_case(s):
    """A run of four or more SHOUTED words becomes plain words; known names inside the run are restored.
    Nothing outside such a run is touched (file names and handles keep their case)."""
    def lower_run(m):
        run = m.group(0).lower()
        for k, v in _NAMES.items():
            run = re.sub(r"\b" + re.escape(k) + r"\b", v, run)
        return run
    return _SHOUT.sub(lower_run, s)


def end_sentence(s):
    s = (s or "").strip()
    if not s:
        return s
    return s if s.endswith(("...", ".", "?", "!")) else s + "."


def cut_words(s, limit):
    """Cut at a word boundary at `limit` characters, never mid-word; a text that fits is returned whole."""
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    head = s[:limit - 3]
    m = re.search(r"\s\S*$", head)
    if m and m.start() > 0:
        head = head[:m.start()]
    head = head.rstrip(" ,;:(")
    return head + "..."


_INTERROGATIVE = re.compile(r"^(?:what|which|should|shall|do you|does|did|is it|is the|are|will|would|can|could|"
                            r"when|where|how|whether|who|why|may)\b", re.I)
_TITLE_LABEL = re.compile(r"^([A-Z][A-Z \-']{2,40}):\s")


def is_question(s):
    return s.rstrip().endswith("?") or bool(_INTERROGATIVE.match(re.sub(r"^(?:question|ask)\s*:\s*", "", s, flags=re.I)))


def ask_pick(text):
    """(index, sentence) of the item's ask: the sentence saying WAITING ON MASON when there is one, else
    the first real question among the first six sentences, else the first sentence."""
    ss = sentences(text)
    if not ss:
        return -1, ""
    for i, s in enumerate(ss[:6]):
        if _WAITING.search(s):
            return i, s
    for i, s in enumerate(ss[:6]):
        if is_question(s) and not _FORM_LABELS.match(s):
            return i, s
    return 0, ss[0]


def _tidy(s):
    s = _sentence_case(s)
    s = re.sub(r"\s+", " ", s).strip(" ,;")
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s


def ask_sentence(text):
    """The item's ask (ask_pick) with lead tags, form labels and the because clause removed, first letter
    capitalised. A short title-like ask gains the item's Options sentence; an ask chosen from later in the
    text gains the first sentence's SHOUTED label ("UPDATE CHECK:") as its subject."""
    ss = sentences(text)
    i, pick = ask_pick(text)
    if i < 0:
        return ""
    s = _WAITING.sub("", pick).strip()
    s = re.sub(r"^(?:question|ask|decision)\s*:\s*", "", s, flags=re.I)
    s = re.sub(r"\s*\bKind\s*:\s*\w+\.?\s*$", "", s, flags=re.I)
    s = re.sub(r"\bSame as:\s*[^.;]+[.;]?", "", s, flags=re.I).strip()
    s = _drop_because(s)
    s = s.lstrip(": ").strip()
    if i > 0:
        m = _TITLE_LABEL.match(ss[0])
        if m and s and not s.lower().startswith(m.group(1).lower()):
            body = s[0].lower() + s[1:] if (s[0].isupper() and not s[:2].isupper()) else s
            s = m.group(1).capitalize() + ": " + body
    if len(s.split()) <= 8:
        for o in ss[:8]:
            if re.match(r"^\s*options?\s*:", o, re.I):
                s = s.rstrip(".") + (" " if s.endswith("?") else ": ") + re.sub(r"^\s*options?\s*:\s*", "", o, flags=re.I)
                break
    return _tidy(s)


def recommendation(text, ask=None):
    """The first sentence, other than the ask sentence itself, that says 'recommend', its because clause
    dropped. `ask` is unused and kept for callers; the ask is skipped by its index."""
    ss = sentences(text)
    skip, _ = ask_pick(text)
    for j, s in enumerate(ss):
        if j == skip or not re.search(r"\brecommend", s, re.I):
            continue
        s = re.sub(r"^\s*recommendation\s*:\s*", "Lane recommends: ", s, flags=re.I)
        s = re.sub(r"^\s*options\s*:\s*", "Options: ", s, flags=re.I)
        s = _drop_because(s)
        return cut_words(_tidy(s), REC_MAX)
    return ""


def item_tags(item):
    text = item.get("text") or ""
    needs = (item.get("needs") or "").lower()
    bucket = (item.get("bucket") or "").lower()
    tags = []
    if bucket == "hands" or "hands" in needs or re.search(r"\bat the mac\b", text, re.I):
        tags.append("At the Mac")
    if bucket == "ear" or "listen" in needs:
        tags.append("Listen")
    if re.search(r"\bKind\s*:\s*send\b", text, re.I) or re.match(r"\s*send\b", strip_lead(text), re.I) \
            or "send" in needs:
        tags.append("Send")
    if re.search(r"\boptional\b", text, re.I):
        tags.append("Optional")
    return tags


# ---------------------------------------------------------------------------------------------
# Terms and similarity (step 4b)
# ---------------------------------------------------------------------------------------------

def _clean_for_terms(text):
    t = strip_lead(text)
    t = re.sub(r"\bSame as:\s*[^.;\n]+", " ", t, flags=re.I)
    t = _FORM_LABELS.sub(" ", t)
    words = []
    for w in t.split():
        if "/" in w or re.search(r"\.(?:md|py|json|h|wav|aiff?|txt|png|html|js|cpp|rs|jsonl)\b", w, re.I):
            continue                                            # a path or a file name
        if re.match(r"^\d{4}-\d{2}-\d{2}", w) or re.match(r"^\d{1,2}:\d{2}", w):
            continue                                            # a date or a time
        wl = w.lower().strip("(),;:.'\"`[]")
        if _HEX.match(wl) and re.search(r"\d", wl) and re.search(r"[a-f]", wl):
            continue                                            # a commit hash or md5
        if re.match(r"^(?:19|20)\d\d$", wl):
            continue                                            # a year
        words.append(w)
    return " ".join(words).lower()


def terms(text):
    """(unigrams, bigrams) of the cleaned text with stopwords out; bigrams over the remaining sequence."""
    seq = []
    for w in _TOKEN.findall(_clean_for_terms(text)):
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) < 2 or w in STOPWORDS:
            continue
        seq.append(w)
    uni = set(seq)
    bi = set(a + " " + b for a, b in zip(seq, seq[1:]))
    return uni, bi


def similarity(a_text, b_text, a_ask=None, b_ask=None):
    """The score, and the shared counts the join rule also reads. See the JOIN_* comment."""
    ua, ba = terms(a_text)
    ub, bb = terms(b_text)
    A, B = ua | ba, ub | bb
    inter = A & B
    shared, shared_bi = len(inter), len(ba & bb)
    ov = len(inter) / min(len(A), len(B)) if A and B else 0.0
    cont = 0.0
    for ask, other in ((a_ask, B), (b_ask, A)):
        if ask is None:
            continue
        u, b = terms(ask)
        T = u | b
        if len(T) >= ASK_MIN_TERMS:
            cont = max(cont, len(T & other) / len(T))
    return {"score": max(ov, cont), "ov": ov, "cont": cont, "shared": shared, "shared_bigrams": shared_bi}


def same_question(a, b):
    s = similarity(a.get("text", ""), b.get("text", ""), a.get("_ask"), b.get("_ask"))
    return (s["score"] >= JOIN_SCORE and s["shared"] >= JOIN_MIN_SHARED
            and s["shared_bigrams"] >= JOIN_MIN_BIGRAMS), s


# ---------------------------------------------------------------------------------------------
# Declared links (step 4a)
# ---------------------------------------------------------------------------------------------

def _link_key(raw):
    v = (raw or "").strip().strip(".;,'\"` ").lower()
    if not v:
        return None
    if re.fullmatch(r"[0-9a-f]{10}", v):
        return ("id", v)
    m = re.fullmatch(r"(?:stack\s*)?(?:row\s*)?#?\s*(\d+[a-z]?)", v)
    if m and re.search(r"stack|row", v):
        return ("row", m.group(1))
    m = re.fullmatch(r"when[- ]home\s*#?\s*(\d+[a-z]?)", v)
    if m:
        return ("wh", m.group(1))
    return ("key", re.sub(r"\s+", " ", v))


def own_keys(item):
    keys = {("id", (item.get("id") or "").lower())}
    text = item.get("text") or ""
    m = re.match(r"\s*\[row (\d+[a-z]?)\]", text)
    if m and item.get("lane") == "stack":
        keys.add(("row", m.group(1)))
    m = re.match(r"\s*\[when home (\d+[a-z]?)\]", text, re.I)
    if m and item.get("lane") == "when-home":
        keys.add(("wh", m.group(1)))
    return keys


def declared_links(item):
    """Keys this item says it is the same question as: every "Same as: X" clause (one X, or several
    split by commas or "and"), and the lab's row-naming convention "[STACK 23]" / "WHEN HOME 2"."""
    text = item.get("text") or ""
    keys = set()
    for m in re.finditer(r"\bsame[ _]as\s*:\s*([^.;\n]+)", text, re.I):
        for part in re.split(r",|\band\b", m.group(1)):
            k = _link_key(part)
            if k:
                keys.add(k)
    if item.get("lane") != "stack":
        for m in re.finditer(r"\bSTACK\s*#?\s*(\d+[a-z]?)\b", text):
            keys.add(("row", m.group(1)))
    if item.get("lane") != "when-home":
        for m in re.finditer(r"\bWHEN HOME\s*#?\s*(\d+[a-z]?)\b", text):
            keys.add(("wh", m.group(1)))
    return keys


# ---------------------------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------------------------

def group_items(items, use_links=True, use_text=True):
    """Union-find over the items; returns groups as lists of items in input order, plus the reason each
    pair joined (for --json and the controls)."""
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    joins = []
    for it in items:
        it["_ask"] = ask_sentence(it.get("text", ""))
    if use_links:
        owners = {}
        for i, it in enumerate(items):
            for k in own_keys(it):
                owners.setdefault(k, []).append(i)
        by_key = {}
        for i, it in enumerate(items):
            for k in declared_links(it):
                if k[0] == "key":
                    by_key.setdefault(k, []).append(i)
                else:
                    for j in owners.get(k, []):
                        if j != i:
                            union(i, j)
                            joins.append((items[i]["id"], items[j]["id"], "declared " + k[0] + " " + k[1]))
        for k, members in by_key.items():
            for j in members[1:]:
                union(members[0], j)
                joins.append((items[members[0]]["id"], items[j]["id"], "declared key " + k[1]))
    if use_text:
        for i in range(n):
            for j in range(i + 1, n):
                ok, s = same_question(items[i], items[j])
                if ok:
                    union(i, j)
                    joins.append((items[i]["id"], items[j]["id"],
                                  "text score %.2f, %d shared, %d pairs" % (s["score"], s["shared"], s["shared_bigrams"])))
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i])
    return [groups[r] for r in sorted(groups)], joins


# ---------------------------------------------------------------------------------------------
# Folds
# ---------------------------------------------------------------------------------------------
_LISTEN_LINE = re.compile(r"^\s*(\d+)\s+files? to hear in\s+(.+?)(?:\s*\[[^\]]*\])?\s*$", re.I | re.S)
_PILE_POINTER = re.compile(r"\blistens?\b.*\bTests and Backups/Pending\b", re.I | re.S)


def fold_listens(items):
    """Every listening-folder item, plus a when-home item that points at the same pile, is one choice."""
    members, rest, folders = [], [], []
    for it in items:
        text = it.get("text") or ""
        m = _LISTEN_LINE.match(text)
        if it.get("lane") == "listens" and m:
            folders.append((int(m.group(1)), os.path.basename(m.group(2).rstrip("/ "))))
            members.append(it)
        elif it.get("bucket") == "ear" and it.get("lane") == "when-home" and _PILE_POINTER.search(text):
            members.append(it)
        else:
            rest.append(it)
    if not members:
        return None, rest
    folders.sort(key=lambda f: (f[0], f[1].lower()))
    total = sum(f for f, _ in folders)
    smallest = folders[:2]
    first = " and ".join("%s (%d files)" % (name, n) for n, name in smallest)
    if len(folders) > 2:
        ask = ("%d folders, %d files to hear; the two smallest, %s, are the ones worth doing first"
               % (len(folders), total, first))
    elif folders:
        ask = "%d folder%s, %d files to hear: %s" % (len(folders), "" if len(folders) == 1 else "s", total, first)
    else:
        ask = "The folders under Tests and Backups/Pending"
    tags = ["Listen"]
    if any(re.search(r"\boptional\b", it.get("text") or "", re.I) for it in members):
        tags.append("Optional")
    pile = {"kind": "pile", "lane": "listens", "label": "Listening pile", "ask": ask, "recommendation": "",
            "tags": tags, "members": members, "folders": len(folders), "files": total,
            "smallest": [{"folder": name, "files": n} for n, name in smallest],
            "note": "%d console items are this one pile" % len(members) if len(members) > 1 else ""}
    return pile, rest


_PROJECT = re.compile(r"^([A-Z][A-Za-z&]{2,}(?: [A-Z][A-Za-z&]+){0,2}):\s")
_NOT_PROJECT = {"Question", "Recommendation", "Because", "Options", "Now", "Consequence", "Consequences",
                "Reversible", "Evidence", "Kind", "Note", "Update", "Same", "Asked", "Disposition"}


def project_label(item):
    if item.get("lane") in ("stack", "when-home", "listens"):
        return None
    m = _PROJECT.match(strip_lead(item.get("text") or ""))
    if not m:
        return None
    label = m.group(1)
    if label.upper() == label or label in _NOT_PROJECT:
        return None
    return label


def _sub_ask(item, label):
    s = item.get("_ask") or ask_sentence(item.get("text", ""))
    s = re.sub(r"^" + re.escape(label) + r"\s*:\s*", "", s)
    s = re.sub(r"\s*\([^)]*\)", "", s)
    s = s.split(";")[0].strip(" .")
    if s and s[0].isupper() and not (len(s) > 1 and s[1].isupper()):
        s = s[0].lower() + s[1:]
    return cut_words(s, SUB_ASK_MAX)


def fold_projects(groups):
    """Groups (singletons, after step 4) whose lead item opens with the same project label in one lane
    become one project line."""
    if not PROJECT_FOLD:
        return groups, []
    by_label, out, folds = {}, [], []
    for g in groups:
        lead = g[0]
        label = project_label(lead) if len(g) == 1 else None
        if label:
            by_label.setdefault((lead.get("owner_lane") or lead.get("lane"), label), []).append(g)
        else:
            out.append(g)
    for (lane, label), gs in by_label.items():
        if len(gs) < 2:
            out.extend(gs)
            continue
        members = [g[0] for g in gs]
        due = ""
        for it in members:
            m = re.search(r"\b(?:bid )?due (\d{1,2} [A-Z][a-z]{2}(?: \d{1,2}(?::\d{2})? ?[AP]M)?)", it.get("text") or "")
            if m:
                due = m.group(1)
                break
        asks = [_sub_ask(it, label) for it in members]
        ask = "%s%s, %d answers: %s" % (label, (", due " + due) if due else "", len(members), "; ".join(asks))
        tags = []
        for it in members:
            for t in item_tags(it):
                if t not in tags:
                    tags.append(t)
        folds.append({"kind": "project", "lane": lane, "label": LANE_LABEL.get(lane, lane), "ask": ask,
                      "recommendation": "", "tags": tags, "members": members, "project": label,
                      "note": "%d console items, one project" % len(members)})
    return out, folds


# ---------------------------------------------------------------------------------------------
# Building the list
# ---------------------------------------------------------------------------------------------

def section_of(lane):
    for name, lanes in SECTIONS:
        if lanes is None or lane in lanes:
            return name
    return "Other"


SUBJECT_SPAN = 60            # a STACK or when-home item's subject is read from this many leading characters


def _label_for(item):
    lane = item.get("lane") or ""
    if lane in ("stack", "when-home"):
        head = strip_lead(item.get("text") or "")[:SUBJECT_SPAN]
        best = None
        for pat, label in STACK_SUBJECTS:
            m = re.search(pat, head, re.I)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), label)
        return best[1] if best else "Coordinator"
    return LANE_LABEL.get(lane, lane.capitalize() if lane else "Coordinator")


def _lead_rank(it):
    """Who speaks for a group: the lane's own decisions_for_mason ask first, then another status field,
    then a STACK row, then a when-home item, then a listening folder."""
    src = it.get("source") or ""
    lane = it.get("lane") or ""
    if lane == "listens":
        return 4
    if lane == "when-home":
        return 3
    if lane == "stack":
        return 2
    return 0 if src.endswith(":decisions_for_mason") else 1


def _ordered(group):
    return sorted(group, key=_lead_rank)          # stable: input order inside one rank


def _lead(group):
    return _ordered(group)[0]


def choice_from_group(group):
    ordered = _ordered(group)
    lead = ordered[0]
    ask = ""
    for it in ordered:                            # the first member that asks a real question speaks
        i, s = ask_pick(it.get("text", ""))
        if i >= 0 and (is_question(s) or _WAITING.search(s)):
            ask = it.get("_ask") or ask_sentence(it.get("text", ""))
            break
    if not ask:
        ask = lead.get("_ask") or ask_sentence(lead.get("text", ""))
    rec = ""
    for it in ordered:
        rec = recommendation(it.get("text", ""))
        if rec:
            break
    tags = []
    for it in group:
        for t in item_tags(it):
            if t not in tags:
                tags.append(t)
    lane = lead.get("lane") or ""
    return {"kind": "group" if len(group) > 1 else "item", "lane": lane, "label": _label_for(lead),
            "ask": cut_words(ask, ASK_MAX), "recommendation": rec, "tags": tags, "members": group,
            "note": "%d console items are this one question" % len(group) if len(group) > 1 else ""}


def build(w, rows=None, use_links=True, use_text=True):
    """The grouped structure from a waiting() result (and conversation rows for the gap line)."""
    items = [dict(it) for it in (w.get("items") or []) if isinstance(it, dict)]
    closing, live = [], []
    for it in items:
        if it.get("may_be_settled") and (it.get("settled_reason") or "").strip():
            closing.append(it)
        else:
            live.append(it)
    for it in items:
        it["_ask"] = ask_sentence(it.get("text", ""))
    pile, rest = fold_listens(live)
    groups, joins = group_items(rest, use_links=use_links, use_text=use_text)
    groups, projects = fold_projects(groups)
    choices = [choice_from_group(g) for g in groups] + projects
    if pile:
        choices.append(pile)
    pos = {it["id"]: i for i, it in enumerate(live)}
    lanes_seen = [l for _, ls in SECTIONS if ls for l in ls]
    lane_rank = {l: i for i, l in enumerate(lanes_seen)}

    def sort_key(c):
        lead = _lead(c["members"]) if c["kind"] != "pile" else c["members"][0]
        lane = c["lane"] if c["kind"] == "pile" else (lead.get("lane") or "")
        return (lane_rank.get(lane, len(lane_rank)), pos.get(lead["id"], 10 ** 9))

    choices.sort(key=sort_key)
    sections = []
    for name, _ in SECTIONS:
        cs = [c for c in choices if section_of(c["lane"]) == name]
        if cs:
            sections.append({"name": name, "choices": cs})
    n = 1
    for s in sections:
        for c in s["choices"]:
            c["n"] = n
            n += 1
    paused = []
    for lane, rep in (w.get("lanes") or {}).items():
        if isinstance(rep, dict) and rep.get("paused"):
            paused.append({"lane": lane, "label": PAUSED_LABEL.get(lane, lane), "asks": rep.get("paused_asks") or 0})
    gaps = []
    for r in rows or []:
        if r.get("waiting_on_you") and (r.get("decisions_waiting") == 0):
            lane = r.get("lane") or ""
            gaps.append({"lane": lane, "title": r.get("title") or lane,
                         "headline": ((r.get("headline") or {}).get("visible") or ""),
                         "paused": any(p["lane"] == lane for p in paused)})
    total = len(items)
    n_choices = sum(len(s["choices"]) for s in sections)
    return {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": total, "settled": len(closing),
            "choices": n_choices, "closing": closing, "sections": sections, "paused": paused, "gaps": gaps,
            "joins": joins, "ok": bool(w.get("ok", True)), "message": w.get("message") or ""}


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------

def _closing_line(it):
    ask = cut_words(it.get("_ask") or ask_sentence(it.get("text", "")), 120)
    return "- %s: %s Closing because %s." % (_label_for(it), end_sentence(ask),
                                              (it.get("settled_reason") or "").strip().rstrip("."))


def choice_line(c, ids=False):
    parts = [end_sentence(c["ask"])]
    if c.get("recommendation"):
        parts.append(end_sentence(c["recommendation"]))
    for t in c.get("tags") or []:
        if t == "At the Mac" and section_of(c["lane"]) == "At the Mac, when home":
            continue                              # the section header already says so
        parts.append(t + ".")
    if c.get("note"):
        parts.append(c["note"] + ".")
    line = "%d. %s: %s" % (c["n"], c["label"], " ".join(parts))
    if ids:
        line += " (ids %s)" % ", ".join(m["id"] for m in c["members"])
    return line


def render(struct, ids=False):
    out = []
    n, m, c = struct["choices"], struct["items"], struct["settled"]
    out.append("Waiting on you: %d choices, grouped from %d console items" % (n, m))
    out.append("The console lists %d items. Grouped by same question, minus %d already settled, that's %d choices. "
               "Full context for each sits on hover in the console." % (m, c, n))
    if not struct.get("ok", True):
        out.append("")
        out.append("The console could not be read: " + (struct.get("message") or "no reason given"))
    if struct["closing"]:
        out.append("")
        out.append("Closing now, not choices (%d):" % len(struct["closing"]))
        for it in struct["closing"]:
            out.append(_closing_line(it))
    for s in struct["sections"]:
        out.append("")
        out.append(s["name"])
        for ch in s["choices"]:
            out.append(choice_line(ch, ids=ids))
    out.append("")
    if struct["paused"]:
        names = []
        for p in struct["paused"]:
            k = p["asks"]
            names.append(p["label"] + (" with %d ask%s held" % (k, "" if k == 1 else "s") if k else ""))
        out.append("Paused lanes: %s. Their asks are kept off this list by your pause." % _join_names(names))
    else:
        out.append("No lane is paused; nothing is held off this list.")
    if struct["gaps"]:
        for g in struct["gaps"]:
            why = " (its lane is paused, so its asks are held)" if g.get("paused") else ""
            out.append("One gap I see: the %s chat's headline says \"%s\" but it has 0 items on the list%s."
                       % (g["title"], g["headline"], why))
    return [dash_free(line) for line in out]


def _join_names(names):
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def to_json(struct, ids=True):
    def choice(c):
        d = {"n": c["n"], "kind": c["kind"], "lane": c["lane"], "label": c["label"], "ask": c["ask"],
             "recommendation": c["recommendation"], "tags": c["tags"], "note": c.get("note", ""),
             "ids": [m["id"] for m in c["members"]], "line": dash_free(choice_line(c, ids=False))}
        for k in ("folders", "files", "smallest", "project"):
            if k in c:
                d[k] = c[k]
        return d
    return {
        "generated": struct["generated"], "ok": struct["ok"], "message": struct["message"],
        "headline": render(struct)[0], "summary": render(struct)[1],
        "items": struct["items"], "settled": struct["settled"], "choices": struct["choices"],
        "closing": [{"id": it["id"], "lane": it.get("lane"), "label": _label_for(it), "ask": it.get("_ask"),
                     "reason": it.get("settled_reason")} for it in struct["closing"]],
        "sections": [{"name": s["name"], "choices": [choice(c) for c in s["choices"]]} for s in struct["sections"]],
        "paused": struct["paused"], "gaps": struct["gaps"],
        "joins": [{"a": a, "b": b, "why": why} for a, b, why in struct["joins"]],
    }


# ---------------------------------------------------------------------------------------------
# Live input
# ---------------------------------------------------------------------------------------------

def load_live():
    import monitor_data as md
    w = md.waiting()
    rows = []
    try:
        rows = md.conversations(w)
    except Exception as ex:                    # the gap line is optional; the list is not
        rows = []
        w = dict(w)
        w["_rows_note"] = "conversation rows unavailable: %s" % ex
    return w, rows


# ---------------------------------------------------------------------------------------------
# --polish (opt-in): the printed lines only, through monitor_actions' headless route
# ---------------------------------------------------------------------------------------------
POLISH_PROMPT = """Rewrite the ASK part of each numbered line below as one plain, complete English sentence a person reads at a
glance. Rules, all of them: keep the number and the label before the first colon exactly; keep every fact, number,
name, file name and quoted phrase; keep the meaning of every option exactly (do not merge or reorder options); keep
the "Lane recommends: ..." sentence word for word; keep every short trailing tag sentence ("At the Mac.", "Listen.",
"Send.", "Optional.", "N console items are this one question.", "N console items, one project.") EXACTLY as separate
sentences at the end, never folded into the ask; add nothing; drop nothing; decide nothing; never use an em dash or
an en dash. Output only the rewritten lines, one per line, same count, same order, nothing else.

{lines}
"""
POLISH_CHUNK = 6                     # lines per model call: measured 51 s for 5 lines on 15 Sep, about 10 s a line
POLISH_CHUNK_TIMEOUT = 120           # per call; a chunk that times out keeps its deterministic lines


def polish(lines, timeout=POLISH_CHUNK_TIMEOUT, chunk=POLISH_CHUNK):
    """Opt-in. The numbered lines go to the headless route in chunks; every chunk that fails, times out or
    comes back with the wrong count keeps its deterministic lines, and the note says how many were polished."""
    numbered = [l for l in lines if re.match(r"^\d+\. ", l)]
    if not numbered:
        return lines, "nothing to polish"
    try:
        import monitor_actions as ma
    except Exception as ex:
        return lines, "polish skipped: monitor_actions could not be imported (%s)" % ex
    got, failed = {}, []
    for start in range(0, len(numbered), chunk):
        part = numbered[start:start + chunk]
        want = [int(re.match(r"^(\d+)\. ", l).group(1)) for l in part]
        try:
            rc, out, err = ma._headless(POLISH_PROMPT.format(lines="\n".join(part)), timeout)
        except Exception as ex:
            failed.append("lines %d to %d: %s" % (want[0], want[-1], type(ex).__name__))
            continue
        if rc is None:
            failed.append("lines %d to %d timed out after %d s" % (want[0], want[-1], timeout))
            continue
        if rc != 0:
            failed.append("lines %d to %d: the route returned %s" % (want[0], want[-1], rc))
            continue
        back = {}
        for l in (out or "").splitlines():
            m = re.match(r"^\s*(\d+)\.\s+(.*\S)\s*$", l)
            if m:
                back[int(m.group(1))] = dash_free(m.group(2))
        if sorted(back) != want:
            failed.append("lines %d to %d came back as %d lines, kept as written" % (want[0], want[-1], len(back)))
            continue
        got.update(back)
    new = []
    for l in lines:
        m = re.match(r"^(\d+)\. ", l)
        if m and int(m.group(1)) in got:
            new.append("%s. %s" % (m.group(1), got[int(m.group(1))]))
        else:
            new.append(l)
    note = "%d of %d lines polished by %s" % (len(got), len(numbered), getattr(ma, "CHECKER_NAME", "the headless route"))
    if failed:
        note += "; " + "; ".join(failed)
    return new, note


# ---------------------------------------------------------------------------------------------
# Predictions (step 10) and the live check
# ---------------------------------------------------------------------------------------------
PREDICTIONS = [
    "P1: today's live console yields between 30 and 38 choices from its item count.",
    "P2: the four live sets each collapse to ONE choice: (i) zone editor ear (STACK row 23 plus two sampler "
    "items); (ii) EQ V2 plan plus STACK row 24 plus the EQ audit item 2 of 2; (iii) sampler private GitHub copy "
    "(STACK row 25 plus a sampler item); (iv) Live's Compressor makeup at Threshold -40, Ratio 10 (comp plus "
    "when-home 9).",
]
LIVE_SETS = [
    ("i", "zone editor ear", lambda t: re.search(r"zone editor", t, re.I) and re.search(r"\broot\b", t, re.I)
     and re.search(r"\bplay\b", t, re.I)),
    ("ii", "EQ V2 plan and the open door", lambda t: re.search(r"\bV2 plan\b", t) or
     (re.search(r"\bEQ\b", t) and re.search(r"\bmodifications\b", t))),
    ("iii", "sampler private GitHub copy", lambda t: re.search(r"private GitHub copy", t, re.I) or
     (re.search(r"\bsampler repo\b", t, re.I) and re.search(r"\bno remote\b", t, re.I))),
    ("iv", "Live's Compressor at Threshold -40, Ratio 10", lambda t: re.search(r"\bcompressor\b", t, re.I)
     and re.search(r"threshold -40", t, re.I) and re.search(r"ratio 10\b", t, re.I)),
]


def live_check(struct, w):
    lines, ok_all = [], True
    n = struct["choices"]
    p1 = 30 <= n <= 38
    ok_all &= p1
    lines.append("%s P1: %d choices from %d items (predicted 30 to 38)" % ("PASS" if p1 else "FAIL", n, struct["items"]))
    where = {}
    for s in struct["sections"]:
        for c in s["choices"]:
            for m in c["members"]:
                where[m["id"]] = c["n"]
    for it in struct["closing"]:
        where[it["id"]] = "closing"
    for tag, name, pred in LIVE_SETS:
        members = [it for it in (w.get("items") or []) if pred(it.get("text") or "")]
        choices = sorted(set(str(where.get(it["id"], "?")) for it in members))
        ok = len(members) >= 2 and len(choices) == 1
        ok_all &= ok
        lines.append("%s P2 set (%s) %s: %d live items in %d choice%s%s" % (
            "PASS" if ok else "FAIL", tag, name, len(members), len(choices), "" if len(choices) == 1 else "s",
            " (" + ", ".join("%s -> %s" % (it["id"], where.get(it["id"], "?")) for it in members) + ")"))
    return lines, ok_all


# ---------------------------------------------------------------------------------------------
# The controls (--selftest). Fixtures only; nothing live is read.
# ---------------------------------------------------------------------------------------------

def _fixture(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def selftest():
    results = []

    def check(name, ok, detail):
        results.append((name, bool(ok), detail))

    fx = _fixture("controls.json")
    struct = build(fx["waiting"], fx.get("conversations") or [])
    lines = render(struct)
    text = "\n".join(lines)
    where = {}
    for s in struct["sections"]:
        for c in s["choices"]:
            for m in c["members"]:
                where[m["id"]] = c["n"]

    # (a) three wordings of one question, three lanes, ONE choice
    a_ids = ["a1a1a1a1a1", "a2a2a2a2a2", "a3a3a3a3a3"]
    a_choices = set(where.get(i) for i in a_ids)
    check("(a) three planted wordings group to one", len(a_choices) == 1 and None not in a_choices,
          "choices %s" % sorted(str(x) for x in a_choices))
    # (b) a fourth ask on a different subject, sharing words, must NOT join
    check("(b) the decoy on another subject stays out", where.get("b4b4b4b4b4") not in a_choices and
          where.get("b4b4b4b4b4") is not None, "decoy in choice %s, group in %s" % (where.get("b4b4b4b4b4"), a_choices))
    # (c) same_as forces a group the text rule misses
    c_ids = ["c1c1c1c1c1", "c2c2c2c2c2"]
    c_choices = set(where.get(i) for i in c_ids)
    struct_nolink = build(fx["waiting"], use_links=False)
    where_nl = {m["id"]: c["n"] for s in struct_nolink["sections"] for c in s["choices"] for m in c["members"]}
    c_apart = len(set(where_nl.get(i) for i in c_ids)) == 2
    check("(c) a planted same_as joins two asks the text rule keeps apart", len(c_choices) == 1 and c_apart,
          "with links %s, without links %s" % (sorted(str(x) for x in c_choices),
                                              sorted(str(where_nl.get(i)) for i in c_ids)))
    # (d) a settled item lands in closing now with its reason
    closing_ids = [it["id"] for it in struct["closing"]]
    check("(d) the settled item is in closing now with its reason",
          "d1d1d1d1d1" in closing_ids and "your answer is in ANSWERS-2026-09-14.md" in text
          and "d1d1d1d1d1" not in where, "closing %s" % closing_ids)
    # (e) three listen folders fold to one line naming the two smallest
    pile = [c for s in struct["sections"] for c in s["choices"] if c["kind"] == "pile"]
    pile_line = choice_line(pile[0]) if pile else ""
    check("(e) three listen folders fold to one line naming the two smallest",
          len(pile) == 1 and pile[0]["folders"] == 3 and pile[0]["files"] == 155
          and "eq (6 files) and comp (14 files)" in pile_line, pile_line[:160])
    # (f) the 170 cut never splits a word and never drops a short ask
    long_item = next(it for it in fx["waiting"]["items"] if it["id"] == "f1f1f1f1f1")
    long_ask = ask_sentence(long_item["text"])
    cut = cut_words(long_ask, ASK_MAX)
    body = cut[:-3] if cut.endswith("...") else cut
    whole = long_ask.startswith(body) and (len(body) == len(long_ask) or not long_ask[len(body)].isalnum())
    short_line = next((l for l in lines if "Name your second favourite autotune?" in l), "")
    check("(f) the %d cut lands on a word boundary and a short ask prints whole" % ASK_MAX,
          len(cut) <= ASK_MAX and whole and len(long_ask) > ASK_MAX and bool(short_line),
          "cut %d chars, ends %r; short ask found %s" % (len(cut), cut[-25:], bool(short_line)))
    # (g) no em or en dash anywhere in the output, though the fixtures plant both
    planted = any("—" in it["text"] or "–" in it["text"] for it in fx["waiting"]["items"])
    check("(g) no em or en dash in the output (both planted in the fixtures)",
          planted and "—" not in text and "–" not in text, "planted %s" % planted)
    # (h) sabotage: with the text rule off, control (a) must FAIL
    sab = build(fx["waiting"], use_text=False)
    where_s = {m["id"]: c["n"] for s in sab["sections"] for c in s["choices"] for m in c["members"]}
    sab_choices = set(where_s.get(i) for i in a_ids)
    check("(h) sabotage: grouping off, control (a) fails", len(sab_choices) == 3, "choices %s" % sorted(sab_choices))
    # (i) the project fold (step 4b): three Chapel asks are one line saying so
    proj = [c for s in struct["sections"] for c in s["choices"] if c["kind"] == "project"]
    check("(i) three same-project asks fold to one line", len(proj) == 1 and len(proj[0]["members"]) == 3
          and "3 console items, one project" in choice_line(proj[0]), choice_line(proj[0])[:150] if proj else "none")
    # (j) the header lines keep their limits and the counts add up
    n_members = sum(len(c["members"]) for s in struct["sections"] for c in s["choices"])
    check("(j) header under %d, summary under %d, every live item in exactly one choice" % (HEADLINE_MAX, SUMMARY_MAX),
          len(lines[0]) < HEADLINE_MAX and len(lines[1]) < SUMMARY_MAX
          and n_members + len(struct["closing"]) == struct["items"],
          "%d and %d chars; %d in choices + %d closing = %d items" % (len(lines[0]), len(lines[1]), n_members,
                                                                     len(struct["closing"]), struct["items"]))
    # (k) paused lanes and the gap line come from the engine's own fields
    check("(k) paused line names the paused lane and the gap line the empty 'Waiting on you' chat",
          "Paused lanes: Room correction with 2 asks held" in text and "One gap I see: the Dreiling_Room chat" in text,
          [l for l in lines if l.startswith("Paused") or l.startswith("One gap")])

    # (l) the lab's row-naming convention: "[STACK 41]" on a lane's ask joins it to STACK row 41 with no
    #     shared wording, and the sabotage (links off) keeps them apart
    l_ids = ["l1l1l1l1l1", "l2l2l2l2l2"]
    l_with = set(where.get(i) for i in l_ids)
    l_without = set(where_nl.get(i) for i in l_ids)
    check("(l) '[STACK 41]' on an ask joins it to row 41; links off keeps them apart",
          len(l_with) == 1 and None not in l_with and len(l_without) == 2,
          "with links %s, without %s" % (sorted(str(x) for x in l_with), sorted(str(x) for x in l_without)))

    out = []
    for name, ok, detail in results:
        out.append("%s %s: %s" % ("PASS" if ok else "FAIL", name, detail))
    out.append("")
    out.append("Predictions (test them with --live-check):")
    out.extend("  " + p for p in PREDICTIONS)
    return out, all(ok for _, ok, _ in results)


# ---------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="the live grouped choice list, in his shape")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ids", action="store_true")
    ap.add_argument("--polish", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--live-check", action="store_true")
    ap.add_argument("--fixture", help="a fixture file instead of the live console (for checks)")
    args = ap.parse_args(argv)

    if args.selftest:
        out, ok = selftest()
        print("\n".join(out))
        return 0 if ok else 1

    if args.fixture:
        fx = _fixture(args.fixture) if not os.path.isabs(args.fixture) else json.load(open(args.fixture))
        w, rows = fx["waiting"], fx.get("conversations") or []
    else:
        w, rows = load_live()
    struct = build(w, rows)

    if args.live_check:
        lines, ok = live_check(struct, w)
        print("\n".join(lines))
        return 0 if ok else 1
    if args.json:
        print(json.dumps(to_json(struct), indent=1, ensure_ascii=False))
        return 0
    lines = render(struct, ids=args.ids)
    if args.polish:
        lines, note = polish(lines)
        lines.append("(" + note + ")")
    print("\n".join(dash_free(l) for l in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
