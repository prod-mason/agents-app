#!/opt/homebrew/bin/python3
"""richtext: agents' Markdown, measured and rendered for Agents.app.

The SOURCE stays plain Markdown text, so the coordinator can read it in a CLI.
This module only measures and renders it. One parser feeds every output:

    parse (raw text) -> block tree -> inline tree
        -> visible_text / visible_len     what a reader sees, markers removed
        -> opening_line                   the Description column's first line
        -> inline_attributed              NSAttributedString for one table cell
        -> to_html                        full HTML page for the hover panel

Supported syntax
    inline : **bold** __bold__  *italic* _italic_  ++underline++  ==highlight==
             `code`  ~~strike~~  [link](url)  <https://autolink>  \\-escapes
             emoji pass through untouched (never normalised, never rewritten)
             stricter than CommonMark where agents' text needs it: 2*3*4 and
             k*1000 keep their *, __init__.py and /_private_/ keep their _,
             C++ and j++ never close an underline
    blocks :# headings, paragraphs, - * + and 1. 1) lists (nested), GitHub pipe
             tables, ``` and ~~~ fenced code, > quotes, --- rules

Security (to_html)
    Agents' text is untrusted. The input is parsed as raw text into a tree; the
    ONLY place text becomes HTML is _esc(), called on every text leaf and every
    attribute value. Markup tags are written by this renderer from the tree,
    never copied from the input, so <script> or <img onerror> in a message can
    only ever come out as visible text. Link targets are allowlisted by scheme
    (http, https, mailto); anything else (javascript:, data:, file:) is shown as
    dim text with a dotted underline and no href. The page carries a Content-Security-Policy
    meta tag with script-src 'none'. --selftest proves this with an HTML parser:
    every tag and attribute in the output must be on a fixed allowlist.

Importing has no side effects. AppKit is imported only inside
inline_attributed() and default_colors().

CLI
    python3 richtext.py --selftest
    python3 richtext.py --render file.md [--title T] [--meta M]
        writes file.html NEXT TO file.md (same folder, same stem)
    python3 richtext.py --corpus [--out DIR]
        runs every function on the latest message of every live session
"""

import html
import re
import sys
import unicodedata

__all__ = [
    "LIMIT", "PALETTE", "visible_text", "visible_len", "grapheme_len", "opening_line",
    "is_complete", "parse_inline", "parse_blocks", "fold_line", "inline_attributed",
    "default_colors", "to_html",
]

LIMIT = 200          # characters a reader counts (grapheme clusters) in the Description title line

# ---------------------------------------------------------------------------
# Palette: one table feeds both the CSS and the NSColors.
# (r, g, b, alpha) in sRGB 0..255.
# ---------------------------------------------------------------------------
PALETTE = {
    "bg":           (0x1C, 0x1C, 0x1F, 1.0),
    "text":         (0xE6, 0xE6, 0xE9, 1.0),
    "strong":       (0xFF, 0xFF, 0xFF, 1.0),
    "heading":      (0xF5, 0xF5, 0xF7, 1.0),
    "dim":          (0x9C, 0x9C, 0xA3, 1.0),
    "rule":         (0x3A, 0x3A, 0x40, 1.0),
    "th_bg":        (0x2A, 0x2A, 0x30, 1.0),
    "highlight_bg": (0xF5, 0xCD, 0x5B, 1.0),   # warm yellow
    "highlight_fg": (0x1B, 0x18, 0x12, 1.0),   # dark text on it (contrast about 11:1)
    "code_fg":      (0xEB, 0xC9, 0x9A, 1.0),
    "code_bg":      (0xFF, 0xFF, 0xFF, 0.09),
    "pre_bg":       (0x14, 0x14, 0x16, 1.0),
    "link":         (0xE6, 0xE6, 0xE9, 1.0),
    "quote_bar":    (0x4A, 0x4A, 0x52, 1.0),
}


def _css_color(key):
    r, g, b, a = PALETTE[key]
    if a >= 1.0:
        return "#%02X%02X%02X" % (r, g, b)
    return "rgba(%d,%d,%d,%.2f)" % (r, g, b, a)


# ---------------------------------------------------------------------------
# Character classes
# ---------------------------------------------------------------------------
_ESCAPABLE = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_CODE_TICK = "`"
_EMPH_CHARS = "*_"            # emphasis runs: 1 = italic, 2 = bold
_PAIR_CHARS = "~=+"           # exact double runs: ~~strike~~ ==mark== ++underline++
_UNDERSCORE_STRICT = True     # _ may not open or close inside a word (snake_case)
_PAIR_KIND = {"~": "del", "=": "mark", "+": "u"}
_MAX_NEST = 24                # deeper emphasis, links, quotes or lists render as plain text
_MAX_URL = 2048               # a link destination longer than this is not a link
_MAX_LINK_NEST = 2            # [a [b](u)](v): links inside link text stop here


def _is_ws(c):
    return c == "" or c.isspace()


def _is_punct(c):
    if not c:
        return False
    return unicodedata.category(c)[0] in "PS"


# ---------------------------------------------------------------------------
# Inline parsing
# Tree nodes:  ["text", s]  ["code", s]  ["link", url, children]
#              [kind, children]  where kind in strong em u mark del
# ---------------------------------------------------------------------------
def _code_close(s, j, run):
    """Index of a backtick run of exactly `run` starting at or after j, or -1."""
    n = len(s)
    m = j
    while m < n:
        if s[m] == _CODE_TICK:
            e = m
            while e < n and s[e] == _CODE_TICK:
                e += 1
            if e - m == run:
                return m
            m = e
        else:
            m += 1
    return -1


def _bracket_pairs(s, code_close):
    """{index of '[': index of its matching ']'} in one linear pass, skipping
    backslash escapes and code spans (so every lookup is O(1))."""
    pairs, stack = {}, []
    n = len(s)
    i = 0
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == _CODE_TICK:
            j = i
            while j < n and s[j] == _CODE_TICK:
                j += 1
            close = code_close(j, j - i)
            i = close + (j - i) if close >= 0 else j
            continue
        if c == "[":
            stack.append(i)
        elif c == "]" and stack:
            pairs[stack.pop()] = i
        i += 1
    return pairs


def _paren_pairs(s):
    """{index of '(': index of its matching ')'} in one linear pass; a newline
    ends every open parenthesis (a link destination never spans lines)."""
    pairs, stack = {}, []
    n = len(s)
    i = 0
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n":
            stack.clear()
        elif c == "(":
            stack.append(i)
        elif c == ")" and stack:
            pairs[stack.pop()] = i
        i += 1
    return pairs


def _link_at(s, i, pairs):
    """s[i] == '['. Returns (end, text, url) for [text](url), else None.
    pairs = (bracket_pairs, paren_pairs), both precomputed for s."""
    n = len(s)
    j = pairs[0].get(i)
    if j is None or j + 1 >= n or s[j + 1] != "(":
        return None
    k = pairs[1].get(j + 1)
    if k is None or k - (j + 2) > _MAX_URL:
        return None
    dest = s[j + 2:k].strip()
    if dest.startswith("<") and ">" in dest:
        dest = dest[1:dest.index(">")]
    elif dest:
        dest = dest.split()[0]
    return k + 1, s[i + 1:j], dest


_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^\s<>]+)>", re.I)

# Literal-run rules. Each is a flag so --selftest can switch it off and prove
# its control fails without it.
_STAR_MATH_LITERAL = True     # 2*3*4, k*1000, pi*f: one * between letters/digits is arithmetic
_PATH_UNDERSCORE_LITERAL = True   # __init__.py, /tmp/__pycache__/, /_private_/ stay as typed
_PLUS_CODE_GUARD = True       # ++ never closes right after a one-letter word (C++, j++, i++)
_ONE_CHAR_UNDERLINE = True    # ...except ++b++ standing alone between word edges (checker, 11 Sep)


def _literal_run(s, c, run, before, after, j):
    """True when a run of * or _ at s[i:j] can never be a delimiter.
    This is stricter than CommonMark on purpose: agents' messages are full of
    arithmetic and file paths, and a number or path Mason reads (or copies)
    must never lose a character."""
    if c == "*" and run == 1 and _STAR_MATH_LITERAL and before.isalnum() and after.isalnum():
        return True
    if c == "_" and _PATH_UNDERSCORE_LITERAL:
        if before == "/":
            return True
        if after in "./" and after and j + 1 < len(s) and s[j + 1].isalnum():
            return True
    return False


def _tokens(s, depth=0):
    out = []
    buf = []
    no_close = set()          # backtick run lengths known to have no closer ahead

    def code_close(j, run):
        if run in no_close:
            return -1
        c = _code_close(s, j, run)
        if c < 0:
            no_close.add(run)
        return c

    if depth < _MAX_LINK_NEST and "[" in s:
        pairs = (_bracket_pairs(s, code_close), _paren_pairs(s) if "](" in s else {})
    else:
        pairs = ({}, {})

    def flush():
        if buf:
            out.append(["text", "".join(buf)])
            buf.clear()

    n = len(s)
    i = 0
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] in _ESCAPABLE:
            buf.append(s[i + 1])
            i += 2
            continue
        if c == _CODE_TICK:
            j = i
            while j < n and s[j] == _CODE_TICK:
                j += 1
            run = j - i
            close = code_close(j, run)
            if close < 0:
                buf.append(s[i:j])
                i = j
                continue
            code = s[j:close].replace("\n", " ")
            if len(code) >= 2 and code[0] == " " and code[-1] == " " and code.strip(" "):
                code = code[1:-1]
            flush()
            out.append(["code", code])
            i = close + run
            continue
        if c == "[" or (c == "!" and i + 1 < n and s[i + 1] == "["):
            at = i + 1 if c == "!" else i
            got = _link_at(s, at, pairs)
            if got:
                end, text, url = got
                flush()
                kids = _parse_inline(text, depth + 1) if text else [["text", url]]
                out.append(["link", url, kids])
                i = end
                continue
        if c == "<":
            m = _AUTOLINK.match(s, i)
            if m:
                flush()
                out.append(["link", m.group(1), [["text", m.group(1)]]])
                i = m.end()
                continue
        if c in _EMPH_CHARS or c in _PAIR_CHARS:
            j = i
            while j < n and s[j] == c:
                j += 1
            run = j - i
            before = s[i - 1] if i > 0 else ""
            after = s[j] if j < n else ""
            if _literal_run(s, c, run, before, after, j):
                buf.append(s[i:j])
                i = j
                continue
            lf =(not _is_ws(after)) and (not _is_punct(after) or _is_ws(before) or _is_punct(before))
            rf = (not _is_ws(before)) and (not _is_punct(before) or _is_ws(after) or _is_punct(after))
            if c in _EMPH_CHARS:
                if c == "_" and _UNDERSCORE_STRICT:
                    can_open = lf and (not rf or _is_punct(before))
                    can_close = rf and (not lf or _is_punct(after))
                else:
                    can_open, can_close = lf, rf
            else:
                if run != 2:
                    buf.append(s[i:j])
                    i = j
                    continue
                if c == "~":
                    can_open, can_close = lf, rf
                else:
                    # == and ++ never open or close inside a word: a==b, C++, i++
                    can_open = lf and (_is_ws(before) or _is_punct(before))
                    can_close = rf and (_is_ws(after) or _is_punct(after))
                    if (c == "+" and _PLUS_CODE_GUARD and before.isalnum()
                            and (i < 2 or not s[i - 2].isalnum())
                            and not (_ONE_CHAR_UNDERLINE and _one_char_underline(s, i, j))):
                        can_close = False     # C++, j++, g++: a one-letter word then ++ is code
            if not (can_open or can_close):
                buf.append(s[i:j])
                i = j
                continue
            flush()
            out.append(["delim", c, run, can_open, can_close, run])
            i = j
            continue
        buf.append(c)
        i += 1
    flush()
    return out


def _one_char_underline(s, i, j):
    """The closing ++ at s[i:j] ends "++x++" where the opening ++ starts at a word edge (line start,
    white space or punctuation other than +) and the close is followed by one: "a ++b++ c". C++ and j++
    have no ++ right before their letter, so the code guard still holds for them."""
    if i < 3 or s[i - 3:i - 1] != "++":
        return False
    lead = s[i - 4] if i >= 4 else ""
    tail = s[j] if j < len(s) else ""
    return (lead == "" or (lead != "+" and (_is_ws(lead) or _is_punct(lead)))) and \
        (tail == "" or (tail != "+" and (_is_ws(tail) or _is_punct(tail))))


def _finalize(toks):
    """Unmatched delimiters become literal text; adjacent text merges.
    Adjacent pieces are collected and joined once, so a long paragraph full of
    unmatched markers costs linear time (repeated += was quadratic)."""
    out = []
    pend = []
    for t in toks:
        k = t[0]
        if k == "delim":
            if t[2] > 0:
                pend.append(t[1] * t[2])
        elif k == "text":
            pend.append(t[1])
        else:
            if pend:
                out.append(["text", "".join(pend)])
                pend = []
            out.append(t)
    if pend:
        out.append(["text", "".join(pend)])
    return out


def _emphasis(toks):
    """Delimiter-stack matching (CommonMark style): each closer pairs with the
    nearest usable opener, so **bold *italic* bold** nests correctly.
    bottom[] remembers, per closer kind, the index below which no opener can
    exist (CommonMark's openers_bottom), keeping the whole search linear.
    Tokens stay at fixed indices, chained by nxt/prv: a match moves its inner
    tokens into one node in the first inner slot and unlinks the rest, so each
    token is absorbed once (a list slice here shifted the whole tail on every
    match, which was quadratic)."""
    n = len(toks)
    nxt = list(range(1, n + 1))
    prv = list(range(-1, n - 1))
    bottom = {}
    i = 0
    while i < n:
        t = toks[i]
        if t[0] != "delim" or not t[4] or t[2] <= 0:
            i = nxt[i]
            continue
        ch = t[1]
        key = (ch, t[3], t[5] % 3)
        opener = None
        j = prv[i]
        lo = bottom.get(key, 0)
        while j >= lo:
            o = toks[j]
            if o[0] == "delim" and o[1] == ch and o[3] and o[2] > 0:
                if ch in _EMPH_CHARS:
                    if ((o[4] or t[3]) and (o[5] + t[5]) % 3 == 0
                            and not (o[5] % 3 == 0 and t[5] % 3 == 0)):
                        j = prv[j]
                        continue
                elif o[2] < 2 or t[2] < 2:
                    j = prv[j]
                    continue
                opener = j
                break
            j = prv[j]
        inner = []
        if opener is not None:
            k = nxt[opener]
            while k != i:
                inner.append(toks[k])
                k = nxt[k]
        if opener is None or not inner:
            bottom[key] = i
            i = nxt[i]
            continue
        nest = max((x[2] for x in inner if len(x) == 3 and x[0] in _NODE_KINDS), default=0) + 1
        if nest > _MAX_NEST:
            bottom[key] = i     # too deep: this closer stays literal text
            i = nxt[i]
            continue
        o = toks[opener]
        if ch in _EMPH_CHARS:
            use = 2 if (o[2] >= 2 and t[2] >= 2) else 1
            kind = "strong" if use == 2 else "em"
        else:
            use = 2
            kind = _PAIR_KIND[ch]
        o[2] -= use
        t[2] -= use
        slot = nxt[opener]
        toks[slot] = [kind, _finalize(inner), nest]
        nxt[slot] = i
        prv[i] = slot
        for k2, v in bottom.items():      # the collapsed range held no openers any more
            if v > slot:
                bottom[k2] = slot
        # i is unchanged: re-examine the closer if it has chars left
    live = []
    k = 0
    while k < n:
        live.append(toks[k])
        k = nxt[k]
    return _finalize(live)


_NODE_KINDS = {"strong", "em", "u", "mark", "del"}


def _parse_inline(s, depth):
    return _emphasis(_tokens(s or "", depth))


def parse_inline(s):
    """Inline tree for one span of Markdown text (see node shapes above).
    Emphasis nodes carry a third element, their nesting depth."""
    return _parse_inline(s, 0)


# ---------------------------------------------------------------------------
# Block parsing
# Blocks: ("p", text) ("h", level, text) ("hr",) ("code", info, lines)
#         ("quote", blocks) ("list", ordered, start, items, tight)
#         ("table", aligns, header_cells, rows)
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*(.*)$")
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_HR_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE_RE = re.compile(r"^ {0,3}>")
_LIST_RE = re.compile(r"^( *)([-*+\u2022]|\d{1,3}[.)])(?:( +)|$)")
_TABLE_RULE_NEEDS_PIPE = True    # a delimiter row must hold a literal |
_CELL_CODE_UNPIPE = True         # \| inside a code span in a table cell shows as |
_TABLE_RULE_RE = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")


def _expand_lead(line):
    lead = re.match(r"[ \t]*", line).group(0)
    if "\t" in lead:
        return lead.expandtabs(4) + line[len(lead):]
    return line


def _dedent(line, n):
    line = _expand_lead(line)
    k = 0
    while k < n and k < len(line) and line[k] == " ":
        k += 1
    return line[k:]


def _fence_body_line(line, ind):
    """A fenced code line keeps its bytes; only the fence's own indent is removed."""
    return _dedent(line, ind) if ind else line


def _fence_open(line):
    m = _FENCE_RE.match(line)
    if not m:
        return None
    fence, info = m.group(2), m.group(3)
    if fence[0] == "`" and "`" in info:
        return None
    return len(m.group(1)), fence, info.strip()


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, buf = [], []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n and s[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if c == _CODE_TICK:
            j = i
            while j < n and s[j] == _CODE_TICK:
                j += 1
            close = _code_close(s, j, j - i)
            if close >= 0:
                span = s[i:close + (j - i)]
                if _CELL_CODE_UNPIPE:
                    span = span.replace("\\|", "|")     # GFM: `a \| b` in a cell shows a | b
                buf.append(span)
                i = close + (j - i)
                continue
            buf.append(s[i:j])
            i = j
            continue
        if c == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _table_at(lines, i):
    """If a GitHub pipe table starts at lines[i], return (block, next_i)."""
    if i + 1 >= len(lines):
        return None
    head, rule = lines[i], lines[i + 1]
    if "|" not in head or not _TABLE_RULE_RE.match(rule) or "-" not in rule:
        return None
    if "|" not in rule and (_TABLE_RULE_NEEDS_PIPE or len(_split_row(head)) != 1):
        return None       # "text |" then "---" is a sentence and a rule, not a table
    hcells = _split_row(head)
    rcells = _split_row(rule)
    if len(hcells) != len(rcells):
        return None
    aligns = []
    for r in rcells:
        r = r.strip()
        if r.startswith(":") and r.endswith(":"):
            aligns.append("c")
        elif r.endswith(":"):
            aligns.append("r")
        else:
            aligns.append("")
    rows = []
    j = i + 2
    while j < len(lines):
        ln = _expand_lead(lines[j])
        if not ln.strip() or "|" not in ln or _starts_block(ln):
            break
        cells = _split_row(ln)
        cells = (cells + [""] * len(hcells))[:len(hcells)]
        rows.append(cells)
        j += 1
    return ("table", aligns, hcells, rows), j


def _starts_block(line):
    return bool(_fence_open(line) or _HR_RE.match(line) or _HEADING_RE.match(line)
                or _QUOTE_RE.match(line) or _LIST_RE.match(line))


def _interrupts_para(line):
    """Can this line end a paragraph it directly follows? Like _starts_block,
    except that an ordered list may only interrupt a paragraph when it starts
    at 1 (CommonMark), so "The count was\\n100. That is high." stays one paragraph."""
    m = _LIST_RE.match(line)
    if m and m.group(2)[0].isdigit() and int(m.group(2)[:-1]) != 1:
        return bool(_fence_open(line) or _HR_RE.match(line) or _HEADING_RE.match(line)
                    or _QUOTE_RE.match(line))
    return _starts_block(line)


def _continues_list(line, ol_next):
    """True when line is an ordered item numbered ol_next, the number after the
    last item of the previous ordered list in the same block sequence. Agents
    resume a numbered list after a lead-in line ("**Worth knowing:**" then
    "6. ..."), and that stays a list even though CommonMark would not allow it."""
    m = _LIST_RE.match(line)
    return bool(m and ol_next is not None and m.group(2)[0].isdigit()
                and int(m.group(2)[:-1]) == ol_next)


def _parse_list(lines, i, depth=0):
    first = _expand_lead(lines[i])
    m = _LIST_RE.match(first)
    ordered = m.group(2)[0].isdigit()
    start = int(m.group(2)[:-1]) if ordered else 1
    base = len(m.group(1))
    items = []
    tight = True
    item_lines_end_blank = False
    n = len(lines)
    while i < n:
        line = _expand_lead(lines[i])
        m = _LIST_RE.match(line)
        if not m or _HR_RE.match(line):
            break
        ind = len(m.group(1))
        if m.group(2)[0].isdigit() != ordered or ind > base + 3:
            break
        if items and item_lines_end_blank:
            tight = False
        spaces = len(m.group(3) or "")
        width = len(m.group(2))
        col = ind + width + (spaces if 1 <= spaces <= 4 else 1)
        item_lines = [line[col:] if len(line) > col else ""]
        i += 1
        saw_blank = False
        while i < n:
            raw = lines[i]
            l2 = _expand_lead(raw)
            if not l2.strip():
                item_lines.append("")
                saw_blank = True
                i += 1
                continue
            ind2 = len(l2) - len(l2.lstrip(" "))
            m2 = _LIST_RE.match(l2)
            if ind2 >= col or (m2 and not _HR_RE.match(l2) and ind2 > base):
                item_lines.append(_dedent(raw, col))
                saw_blank = False
                i += 1
                continue
            same_kind = bool(m2) and m2.group(2)[0].isdigit() == ordered
            if same_kind or saw_blank or _interrupts_para(l2) or _table_at(lines, i):
                break
            item_lines.append(l2.strip())          # lazy continuation of the text
            i += 1
        item_lines_end_blank = bool(item_lines) and item_lines[-1] == ""
        while item_lines and item_lines[-1] == "":
            item_lines.pop()
        if "" in item_lines and not _only_nested_gaps(item_lines):
            tight = False          # a blank line separates two paragraphs of one item
        items.append(parse_blocks(item_lines, depth + 1))
    return ("list", ordered, start, items, tight), i


def _only_nested_gaps(item_lines):
    """True when every blank line in an item sits next to a nested list line."""
    for k, x in enumerate(item_lines):
        if x == "":
            nxt = item_lines[k + 1] if k + 1 < len(item_lines) else ""
            if not _LIST_RE.match(_expand_lead(nxt)):
                return False
    return True


def parse_blocks(lines, depth=0):
    """Block tree for a list of lines (see block shapes above). Quotes and
    lists nested deeper than _MAX_NEST become one plain paragraph."""
    if isinstance(lines, str):
        lines = _lines(lines)
    if depth > _MAX_NEST:
        text = "\n".join(x.strip() for x in lines if x.strip())
        return [("p", text)] if text else []
    blocks = []
    para = []
    ol_next = None          # number after the last ordered list's last item

    def end_para():
        if para:
            blocks.append(("p", "\n".join(x.strip() for x in para)))
            para.clear()

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        line = _expand_lead(raw)
        if not line.strip():
            end_para()
            i += 1
            continue
        f = _fence_open(line)
        if f:
            end_para()
            ind, fence, info = f
            close = re.compile(r"^ {0,3}" + re.escape(fence[0]) + "{%d,}[ \t]*$" % len(fence))
            body = []
            i += 1
            while i < n:
                if close.match(_expand_lead(lines[i])):
                    i += 1
                    break
                body.append(_fence_body_line(lines[i], ind))
                i += 1
            blocks.append(("code", info, body))
            continue
        if _HR_RE.match(line):
            end_para()
            blocks.append(("hr",))
            i += 1
            continue
        m = _HEADING_RE.match(line)
        if m:
            end_para()
            blocks.append(("h", len(m.group(1)), (m.group(2) or "").strip()))
            i += 1
            continue
        if _QUOTE_RE.match(line):
            end_para()
            q = []
            while i < n:
                l2 = _expand_lead(lines[i])
                if _QUOTE_RE.match(l2):
                    q.append(re.sub(r"^ {0,3}> ?", "", l2))
                    i += 1
                elif l2.strip() and q and q[-1].strip() and not _interrupts_para(l2):
                    q.append(l2)            # lazy continuation
                    i += 1
                else:
                    break
            blocks.append(("quote", parse_blocks(q, depth + 1)))
            continue
        t = _table_at(lines, i)
        if t:
            end_para()
            blocks.append(t[0])
            i = t[1]
            continue
        if _LIST_RE.match(line) and (not para or _interrupts_para(line)
                                     or _continues_list(line, ol_next)):
            end_para()
            blk, i = _parse_list(lines, i, depth)
            blocks.append(blk)
            if blk[1]:
                ol_next = blk[2] + len(blk[3])
            continue
        para.append(line)
        i += 1
    end_para()
    return blocks


_SURROGATE_RE = re.compile("[\ud800-\udfff]")
_BOM = "﻿"                            # dropped when it opens a message
_INVISIBLE = "﻿​‌⁠"    # BOM, zero-width space / non-joiner, word joiner


def _desurrogate(s):
    """Lone UTF-16 surrogates (a JSON transcript can hold them) become U+FFFD,
    so every string this module returns encodes as UTF-8."""
    return _SURROGATE_RE.sub("�", s) if s else (s or "")


def _lines(md):
    md = _desurrogate(md or "")
    if _BOM and md.startswith(_BOM):
        md = md[len(_BOM):]
    return md.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _trim(s):
    """strip() plus the invisible characters in _INVISIBLE, at both ends."""
    while True:
        t = s.strip()
        if _INVISIBLE:
            t = t.strip(_INVISIBLE)
        if t == s:
            return t
        s = t


_FOLD_RE = re.compile("[ \t]*[\n\r\x0b\x0c\x1c\x1d\x1e\x85  ]+[ \t]*")


def fold_line(md):
    """The one-line form a table cell shows: every line break (\\r\\n, \\r, \\n,
    U+2028 and the other separators) together with the blanks around it folds
    to one space, and a tab becomes a space. inline_attributed(md) draws
    exactly visible_text(fold_line(md))."""
    s = _desurrogate(md or "").strip()
    if _BOM and s.startswith(_BOM):
        s = s[len(_BOM):]
    return _FOLD_RE.sub(" ", s).replace("\t", " ")


# ---------------------------------------------------------------------------
# Runs: (text, style) pairs. visible_text and inline_attributed both read them,
# so the cell and the measurement can never disagree.
# ---------------------------------------------------------------------------
_EMPTY = frozenset()


def _runs_inline(nodes, style, out):
    for nd in nodes:
        k = nd[0]
        if k == "text":
            out.append((nd[1], style))
        elif k == "code":
            out.append((nd[1], style | {"code"}))
        elif k == "link":
            _runs_inline(nd[2], style | ({"link"} if _safe_url(nd[1]) else {"link", "blocked"}), out)
        else:
            _runs_inline(nd[1], style | {k}, out)


def _runs_blocks(blocks, out, style=_EMPTY, indent=""):
    for bi, b in enumerate(blocks):
        if bi:
            out.append(("\n", style))
        k = b[0]
        if k == "p":
            _runs_inline(parse_inline(b[1]), style, out)
        elif k == "h":
            _runs_inline(parse_inline(b[2]), style | {"h"}, out)
        elif k == "hr":
            pass
        elif k == "code":
            out.append(("\n".join(b[2]), style | {"code", "pre"}))
        elif k == "quote":
            _runs_blocks(b[1], out, style | {"quote"}, indent)
        elif k == "list":
            ordered, start, items = b[1], b[2], b[3]
            for ii, item in enumerate(items):
                if ii:
                    out.append(("\n", style))
                marker = ("%d. " % (start + ii)) if ordered else "\u2022 "
                out.append((indent + marker, style | {"marker"}))
                _runs_blocks(item, out, style, indent + "  ")
        elif k == "table":
            _, _, head, rows = b
            for ci, cell in enumerate(head):
                if ci:
                    out.append(("\t", style))
                _runs_inline(parse_inline(cell), style | {"th"}, out)
            for row in rows:
                out.append(("\n", style))
                for ci, cell in enumerate(row):
                    if ci:
                        out.append(("\t", style))
                    _runs_inline(parse_inline(cell), style, out)


def _runs(md):
    out = []
    _runs_blocks(parse_blocks(_lines(md)), out)
    return out


# ---------------------------------------------------------------------------
# How many characters a reader sees: grapheme clusters
# ---------------------------------------------------------------------------
# Python's len() counts code points, so one emoji could cost 7 of the 50 a
# headline gets (GPT-5.6 Sol review, 15 Sep). A reader counts what is DRAWN:
# one family, one flag, one accented letter. These are Unicode's extended
# grapheme clusters (UAX #29), clustered here by hand because neither python3
# on this Mac has the `regex` or `grapheme` module. Checked against Foundation's
# own composed character sequences in the planted controls.
_RI_RANGE = (0x1F1E6, 0x1F1FF)                 # regional indicators, a flag is two
_EXTEND_RANGES = ((0xFE00, 0xFE0F),            # variation selectors 1 to 16
                  (0xE0100, 0xE01EF),          # variation selectors 17 to 256
                  (0x1F3FB, 0x1F3FF),          # skin tone modifiers
                  (0xE0020, 0xE007F))          # tag characters (the England flag and friends)
_HANGUL = ((0x1100, 0x115F, "L"), (0xA960, 0xA97C, "L"), (0x1160, 0x11A7, "V"), (0xD7B0, 0xD7C6, "V"),
           (0x11A8, 0x11FF, "T"), (0xD7CB, 0xD7FB, "T"))
# Extended_Pictographic, wide enough for the GB11 emoji-ZWJ rule; it decides only
# whether a ZWJ joins two pictures, never whether something is text.
_PICTO_RANGES = ((0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122),
                 (0x2139, 0x2139), (0x2194, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328), (0x2388, 0x2388),
                 (0x23CF, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2), (0x25AA, 0x25FE), (0x2600, 0x27BF),
                 (0x2934, 0x2935), (0x2B00, 0x2BFF), (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3297),
                 (0x3299, 0x3299), (0x1F000, 0x1FAFF), (0x1FC00, 0x1FFFD))
_GB_CACHE = {}


def _in(cp, ranges):
    return any(a <= cp <= b for a, b in ranges)


def _is_picto(ch):
    return _in(ord(ch), _PICTO_RANGES)


def _gb_class(ch):
    """The character's grapheme break class: CR, LF, Control, Extend, ZWJ, SpacingMark, RI, one of the
    Hangul classes, or Other."""
    c = _GB_CACHE.get(ch)
    if c is not None:
        return c
    cp = ord(ch)
    if cp == 0x0D:
        c = "CR"
    elif cp == 0x0A:
        c = "LF"
    elif cp == 0x200D:
        c = "ZWJ"
    elif _in(cp, (_RI_RANGE,)):
        c = "RI"
    elif cp == 0x200C or _in(cp, _EXTEND_RANGES):
        c = "Extend"                               # before Control: tags and U+200C are Cf
    else:
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Me"):
            c = "Extend"
        elif cat in ("Cc", "Cf", "Zl", "Zp"):
            c = "Control"                          # a BOM or a paragraph separator stands alone
        elif cat == "Mc":
            c = "SpacingMark"
        else:
            c = next((k for a, b, k in _HANGUL if a <= cp <= b), None) \
                or ("LV" if 0xAC00 <= cp <= 0xD7A3 and (cp - 0xAC00) % 28 == 0
                    else "LVT" if 0xAC00 <= cp <= 0xD7A3 else "Other")
    if len(_GB_CACHE) < 4096:
        _GB_CACHE[ch] = c
    return c


def _hangul_end(s, i):
    j, n = i, len(s)
    while j < n and _gb_class(s[j]) == "L":
        j += 1
    if j < n and _gb_class(s[j]) in ("LV", "LVT"):
        if _gb_class(s[j]) == "LV":
            j += 1
            while j < n and _gb_class(s[j]) == "V":
                j += 1
        else:
            j += 1
    else:
        while j < n and _gb_class(s[j]) == "V":
            j += 1
    while j < n and _gb_class(s[j]) == "T":
        j += 1
    return max(j, i + 1)


def _cluster_end(s, i):
    """Where the grapheme cluster starting at i ends."""
    n = len(s)
    cls = _gb_class(s[i])
    if cls == "CR":
        return i + 2 if i + 1 < n and s[i + 1] == "\n" else i + 1
    if cls in ("LF", "Control"):
        return i + 1
    if cls in ("L", "V", "T", "LV", "LVT"):
        j = _hangul_end(s, i)
    elif cls == "RI":
        j = i + 2 if i + 1 < n and _gb_class(s[i + 1]) == "RI" else i + 1
    else:
        j = i + 1
    picto = _is_picto(s[i])
    while j < n:
        k = _gb_class(s[j])
        if k in ("Extend", "SpacingMark"):
            j += 1
        elif k == "ZWJ":
            if picto and j + 1 < n and _is_picto(s[j + 1]):
                j += 2                             # GB11: one picture joined to the next
            else:
                j += 1
        else:
            break
    return j


def grapheme_len(s):
    """How many characters a reader sees in s: extended grapheme clusters. A skin-toned thumbs up is
    1, a four-person ZWJ family is 1, a flag is 1, "e" with a combining accent is 1.

    SPEED. Nothing below U+0300 can ever join the character before it (the combining marks, the Hangul
    parts, the regional indicators, ZWJ and the variation selectors all sit above it), so plain text
    costs one comparison a character and only the real clusters are walked. An all-ASCII line is
    counted straight from len(), which keeps the 180,000-character line in the timing control at
    0.001 s instead of 0.25 s."""
    s = s or ""
    if s.isascii():
        return len(s) - s.count("\r\n")           # one cluster each, CR LF the only pair
    n, i, out = len(s), 0, 0
    while i < n:
        c = s[i]
        if c != "\r" and ord(c) < 0x300 and (i + 1 >= n or ord(s[i + 1]) < 0x300):
            i += 1
        else:
            i = _cluster_end(s, i)
        out += 1
    return out


def visible_text(md):
    """The text as a reader sees it: Markdown markers removed.

    Inline markers (** * _ ++ == ~~ ` [..](..)) disappear; a heading loses its
    #s, a quote its >, a bullet becomes "\u2022 ", an ordered item keeps "N. ",
    table cells are separated by a tab and fence lines vanish while the code
    inside stays. Emoji pass through unchanged.

    Length unit: see visible_len. This function returns the text itself, so
    len() on it counts code points, of which one drawn emoji can be several.
    """
    return "".join(t for t, _ in _runs(md))


def visible_len(md):
    """How many characters a READER counts in visible_text(md): grapheme
    clusters (grapheme_len), so a thumbs up with a skin tone is 1 and a
    four-person ZWJ family is 1. Until 15 Sep this was len(), which counted
    code points and charged that family 7 of a headline's 50."""
    return grapheme_len(visible_text(md))


# ---------------------------------------------------------------------------
# Opening line
# ---------------------------------------------------------------------------
_TERMINALS = ".!?"
_CLOSERS = "\"')]}\u201d\u2019\u00bb"
_EMOJI_TAIL = set("\ufe0f\ufe0e\u200d\u20e3") | {chr(c) for c in range(0x1F3FB, 0x1F400)} \
    | {chr(c) for c in range(0xE0020, 0xE0080)}
# Characters drawn as emoji WITHOUT a following U+FE0F: the whole pictograph
# plane, plus the Basic Multilingual Plane's Emoji_Presentation=Yes set (checked
# against ICU, Unicode 17). Text-style symbols such as a check mark, the command
# key or an arrow are not here; they count only when U+FE0F follows them.
_EMOJI_RANGES = ((0x1F000, 0x1FAFF),
                 (0x231A, 0x231B), (0x23E9, 0x23EC), (0x23F0, 0x23F0), (0x23F3, 0x23F3),
                 (0x25FD, 0x25FE), (0x2614, 0x2615), (0x2648, 0x2653), (0x267F, 0x267F),
                 (0x2693, 0x2693), (0x26A1, 0x26A1), (0x26AA, 0x26AB), (0x26BD, 0x26BE),
                 (0x26C4, 0x26C5), (0x26CE, 0x26CE), (0x26D4, 0x26D4), (0x26EA, 0x26EA),
                 (0x26F2, 0x26F3), (0x26F5, 0x26F5), (0x26FA, 0x26FA), (0x26FD, 0x26FD),
                 (0x2705, 0x2705), (0x270A, 0x270B), (0x2728, 0x2728), (0x274C, 0x274C),
                 (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757), (0x2795, 0x2797),
                 (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50),
                 (0x2B55, 0x2B55))
_VS16_ANY_BASE = True         # any character followed by U+FE0F is drawn as an emoji
_ELLIPSES = ("...", "\u2026")  # a line that trails off is not a finished statement


def _ends_with_emoji(s):
    """Read only: looks at the tail, never returns or stores a modified copy."""
    k = len(s)
    vs16 = keycap = False
    while k and s[k - 1] in _EMOJI_TAIL:
        vs16 = vs16 or s[k - 1] == "\ufe0f"
        keycap = keycap or s[k - 1] == "\u20e3"
        k -= 1
    if keycap:
        return True
    if not k:
        return False
    if vs16 and _VS16_ANY_BASE:
        return True
    cp = ord(s[k - 1])
    if any(a <= cp <= b for a, b in _EMOJI_RANGES):
        return True
    return vs16 and unicodedata.category(s[k - 1]) == "So"


def is_complete(visible):
    """A finished statement: ends with . ! or ? or with an emoji, either one
    optionally followed by closing quotes, parens or brackets ("(done.)" and
    "(done \U0001F389)" both count). A trailing ellipsis, "..." or "\u2026", trails
    off and does not count. Judged on VISIBLE text, so **Done.** counts and
    "Summary:" does not."""
    s = (visible or "").rstrip()
    k = len(s)
    while k and s[k - 1] in _CLOSERS:
        k -= 1
    core = s[:k]
    if not core:
        return False
    if _ends_with_emoji(core):
        return True
    if _ELLIPSES and core.endswith(_ELLIPSES):
        return False
    return core[-1] in _TERMINALS


_OPENING_SKIPS_EMPTY = True   # skip fence lines, ---, bare # or >, zero-width-only lines


def opening_line(md):
    """The first line of a message that shows any text, measured for the
    Description column.

    Returns dict(line, visible_len, complete, ok, code):
      line         the raw Markdown line, trimmed of whitespace and zero-width
                   characters, NEVER cut. Lines that show nothing are skipped:
                   blank or zero-width-only lines, a code fence line, a ---
                   rule, a bare # or >.
      visible_len  visible_len(fold_line(line)): the characters a reader counts,
                   grapheme clusters (see visible_len). inline_attributed(line)
                   draws exactly this text, but its own length() counts UTF-16
                   units, which is larger wherever an emoji is drawn
      complete     is_complete(that visible text), but always False when code
      ok           complete and visible_len <= LIMIT (200)
      code         True when that line sits inside a fenced code block, i.e. the
                   message opens with code. A code line is not a statement,
                   whatever it ends with, so complete and ok are False.
    """
    line, code, vis = "", False, None
    fence = None
    for raw in _lines(md):
        t = _trim(raw)
        if not _OPENING_SKIPS_EMPTY:
            if t:
                line = t
                break
            continue
        if fence is not None:
            if fence.match(_expand_lead(raw)):
                fence = None
            elif t:
                line, code = t, True
                break
            continue
        if not t:
            continue
        f = _fence_open(_expand_lead(raw))
        if f:
            fence = re.compile(r"^ {0,3}" + re.escape(f[1][0]) + "{%d,}[ \t]*$" % len(f[1]))
            continue
        vis = visible_text(fold_line(t))     # folding only turns blanks into spaces,
        if not _trim(vis):                   # so it cannot change whether text shows
            vis = None
            continue
        line = t
        break
    if vis is None:
        vis = visible_text(fold_line(line))
    n = grapheme_len(vis)
    done = (not code) and is_complete(vis)
    return {"line": line, "visible_len": n, "complete": done, "ok": done and n <= LIMIT,
            "code": code}


# ---------------------------------------------------------------------------
# NSAttributedString for one table cell
# ---------------------------------------------------------------------------
def default_colors():
    """PALETTE as NSColors (sRGB). Keys: text strong heading dim highlight_bg
    highlight_fg code_fg code_bg link, plus the HTML-only ones."""
    from AppKit import NSColor
    return {k: NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255.0, g / 255.0, b / 255.0, a)
            for k, (r, g, b, a) in PALETTE.items()}


def inline_attributed(md, font_size=13.0, colors=None, truncate=True):
    """NSAttributedString for ONE line of Markdown in a table cell on a dark
    background. Line breaks (\\r, \\n, U+2028...) and tabs fold to spaces (see
    fold_line); a leading heading/quote/bullet marker is rendered the way
    visible_text shows it, so str(result.string()) == visible_text(fold_line(md))
    always.

    bold (and headings, table headers) -> bold system font, brighter white
    italic -> italic face (oblique fallback if the face has none)
    underline / links -> single underline;  strike -> strikethrough, dimmed
    highlight -> warm yellow background with dark text (wins over other colours)
    code -> monospaced, subtle light background, warm text
    emoji -> untouched; Cocoa's font fallback draws them in colour
    colors: dict of NSColor overriding default_colors() keys.
    truncate: tail-truncate with an ellipsis when the cell is too narrow.
    """
    import AppKit as A
    pal = default_colors()
    if colors:
        pal.update(colors)
    line = fold_line(md)
    out = A.NSMutableAttributedString.alloc().init()
    para = None
    if truncate:
        para = A.NSMutableParagraphStyle.alloc().init()
        para.setLineBreakMode_(A.NSLineBreakByTruncatingTail)
    fonts = {}

    def font(bold, italic, mono):
        key = (bold, italic, mono)
        if key not in fonts:
            weight = A.NSFontWeightBold if bold else A.NSFontWeightRegular
            if mono:
                f = A.NSFont.monospacedSystemFontOfSize_weight_(font_size * 0.92, weight)
            else:
                f = A.NSFont.systemFontOfSize_weight_(font_size, weight)
            oblique = False
            if italic:
                d = f.fontDescriptor()
                g = A.NSFont.fontWithDescriptor_size_(
                    d.fontDescriptorWithSymbolicTraits_(d.symbolicTraits() | A.NSFontDescriptorTraitItalic),
                    f.pointSize())
                if g is not None and g.fontDescriptor().symbolicTraits() & A.NSFontDescriptorTraitItalic:
                    f = g
                else:
                    oblique = True
            fonts[key] = (f, oblique)
        return fonts[key]

    for text, st in _runs(line):
        if not text:
            continue
        bold = bool(st & {"strong", "h", "th"})
        f, oblique = font(bold, "em" in st, "code" in st)
        if "mark" in st:
            fg = pal["highlight_fg"]
        elif "code" in st:
            fg = pal["code_fg"]
        elif "del" in st or "quote" in st or "marker" in st or "blocked" in st:
            fg = pal["dim"]
        elif bold:
            fg = pal["strong"]
        elif "link" in st:
            fg = pal["link"]
        else:
            fg = pal["text"]
        attrs = {A.NSFontAttributeName: f, A.NSForegroundColorAttributeName: fg}
        if para is not None:
            attrs[A.NSParagraphStyleAttributeName] = para
        if oblique:
            attrs[A.NSObliquenessAttributeName] = 0.18
        if "mark" in st:
            attrs[A.NSBackgroundColorAttributeName] = pal["highlight_bg"]
        elif "code" in st:
            attrs[A.NSBackgroundColorAttributeName] = pal["code_bg"]
        if "blocked" in st and "u" not in st:
            attrs[A.NSUnderlineStyleAttributeName] = A.NSUnderlineStyleSingle | A.NSUnderlineStylePatternDot
        elif "u" in st or "link" in st:
            attrs[A.NSUnderlineStyleAttributeName] = A.NSUnderlineStyleSingle
        if "del" in st:
            attrs[A.NSStrikethroughStyleAttributeName] = A.NSUnderlineStyleSingle
        out.appendAttributedString_(A.NSAttributedString.alloc().initWithString_attributes_(text, attrs))
    return out


# ---------------------------------------------------------------------------
# HTML for the hover panel
# ---------------------------------------------------------------------------
def _esc(s):
    """THE escape point: every text leaf and attribute value passes here.
    Lone surrogates become U+FFFD here too, so title and meta are covered."""
    return html.escape(_desurrogate(s), quote=True)


_SAFE_URL = re.compile(r"^(?:https?://|mailto:)", re.I)


def _safe_url(url):
    return bool(_SAFE_URL.match(url or ""))


_INLINE_TAG = {"strong": "strong", "em": "em", "u": "u", "mark": "mark", "del": "del"}


def _html_inline(nodes):
    parts = []
    for nd in nodes:
        k = nd[0]
        if k == "text":
            parts.append(_esc(nd[1]).replace("\n", "<br>\n"))
        elif k == "code":
            parts.append("<code>" + _esc(nd[1]) + "</code>")
        elif k == "link":
            inner = _html_inline(nd[2])
            if _safe_url(nd[1]):
                parts.append('<a href="%s" rel="noopener">%s</a>' % (_esc(nd[1]), inner))
            else:
                parts.append('<span class="link">%s</span>' % inner)
        else:
            tag = _INLINE_TAG[k]
            parts.append("<%s>%s</%s>" % (tag, _html_inline(nd[1]), tag))
    return "".join(parts)


def _html_blocks(blocks, tight=False):
    out = []
    for bi, b in enumerate(blocks):
        k = b[0]
        if k == "p":
            inner = _html_inline(parse_inline(b[1]))
            out.append(inner if (tight and bi == 0) else "<p>%s</p>" % inner)
        elif k == "h":
            out.append("<h%d>%s</h%d>" % (b[1], _html_inline(parse_inline(b[2])), b[1]))
        elif k == "hr":
            out.append("<hr>")
        elif k == "code":
            out.append("<pre><code>%s</code></pre>" % _esc("\n".join(b[2])))
        elif k == "quote":
            out.append("<blockquote>%s</blockquote>" % _html_blocks(b[1]))
        elif k == "list":
            ordered, start, items, is_tight = b[1], b[2], b[3], b[4]
            if ordered:
                open_tag = '<ol start="%d">' % start if start != 1 else "<ol>"
            else:
                open_tag = "<ul>"
            lis = "".join("<li>%s</li>" % _html_blocks(item, tight=is_tight) for item in items)
            out.append(open_tag + lis + ("</ol>" if ordered else "</ul>"))
        elif k == "table":
            _, aligns, head, rows = b

            def cell(tag, text, a):
                cls = ' class="%s"' % a if a else ""
                return "<%s%s>%s</%s>" % (tag, cls, _html_inline(parse_inline(text)), tag)
            thead = "<tr>%s</tr>" % "".join(cell("th", c, aligns[i]) for i, c in enumerate(head))
            tbody = "".join("<tr>%s</tr>" % "".join(cell("td", c, aligns[i]) for i, c in enumerate(r))
                            for r in rows)
            out.append('<div class="tw"><table><thead>%s</thead><tbody>%s</tbody></table></div>'
                       % (thead, tbody))
    return "\n".join(out)


_CSP = ("default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
        "font-src 'none'; connect-src 'none'; media-src 'none'; object-src 'none'; "
        "frame-src 'none'; base-uri 'none'; form-action 'none'")

_FONT = ('-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", '
         '"Apple Color Emoji", sans-serif')
_MONO = 'ui-monospace, "SF Mono", Menlo, monospace'


def _css():
    c = _css_color
    return """
:root { color-scheme: dark; }
html, body { margin: 0; background: %(bg)s; color: %(text)s; }
body { font: 14.5px/1.6 %(font)s; -webkit-font-smoothing: antialiased; }
.doc { max-width: 640px; margin: 0 auto; padding: 16px 20px 24px; overflow-wrap: anywhere; }
.top { margin: 0 0 14px; padding: 0 0 9px; border-bottom: 1px solid %(rule)s; }
.top .title { font-size: 12px; font-weight: 600; color: %(text)s; letter-spacing: .01em; }
.top .meta { font-size: 11.5px; color: %(dim)s; margin-top: 1px; }
.body > :first-child { margin-top: 0; }
.body > :last-child { margin-bottom: 0; }
p { margin: 0 0 .75em; }
h1, h2, h3, h4, h5, h6 { color: %(heading)s; line-height: 1.3; margin: 1.1em 0 .45em; font-weight: 650; }
h1 { font-size: 1.3em; } h2 { font-size: 1.17em; } h3 { font-size: 1.06em; }
h4, h5, h6 { font-size: 1em; color: %(text)s; }
strong { color: %(strong)s; font-weight: 650; }
em { font-style: italic; }
u { text-decoration: underline; text-decoration-thickness: 1.5px; text-underline-offset: 2px; }
mark { background: %(hl_bg)s; color: %(hl_fg)s; padding: 0 .22em; border-radius: 3px;
       -webkit-box-decoration-break: clone; box-decoration-break: clone; }
mark *, mark strong, mark code, mark del, mark a, mark .link { color: %(hl_fg)s; }
mark code { background: rgba(0,0,0,.10); }
del { color: %(dim)s; }
code { font-family: %(mono)s; font-size: .88em; background: %(code_bg)s; color: %(code_fg)s;
       padding: .1em .35em; border-radius: 4px; }
pre { background: %(pre_bg)s; border: 1px solid %(rule)s; border-radius: 8px; padding: 10px 12px;
      margin: 0 0 .9em; overflow-x: auto; }
pre code { background: none; padding: 0; color: %(text)s; font-size: 12.5px; line-height: 1.5;
           white-space: pre; overflow-wrap: normal; }
blockquote { margin: 0 0 .8em; padding: .05em 0 .05em 12px; border-left: 3px solid %(quote_bar)s;
             color: %(dim)s; }
blockquote strong { color: %(text)s; }
ul, ol { margin: 0 0 .8em; padding-left: 1.45em; }
li { margin: .22em 0; }
li > ul, li > ol { margin: .2em 0 .25em; }
li > p { margin: .3em 0; }
.tw { overflow-x: auto; margin: 0 0 .9em; }
table { border-collapse: collapse; font-size: .93em; }
th, td { border: 1px solid %(rule)s; padding: 5px 9px; text-align: left; vertical-align: top; }
th { background: %(th_bg)s; color: %(strong)s; font-weight: 600; }
th.c, td.c { text-align: center; } th.r, td.r { text-align: right; }
a { color: %(link)s; text-decoration: underline; text-decoration-color: %(dim)s;
    text-underline-offset: 2px; }
%(blocked)s
hr { border: 0; border-top: 1px solid %(rule)s; margin: 1em 0; }
""" % {"bg": c("bg"), "text": c("text"), "strong": c("strong"), "heading": c("heading"),
       "dim": c("dim"), "rule": c("rule"), "th_bg": c("th_bg"), "hl_bg": c("highlight_bg"),
       "hl_fg": c("highlight_fg"), "code_fg": c("code_fg"), "code_bg": c("code_bg"),
       "pre_bg": c("pre_bg"), "link": c("link"), "quote_bar": c("quote_bar"),
       "font": _FONT, "mono": _MONO, "blocked": _BLOCKED_LINK_CSS % {"dim": c("dim")}}


# A link whose scheme is refused (javascript:, data:, file:) has no href; it is
# drawn dim with a dotted underline so it never looks like a working link.
_BLOCKED_LINK_CSS = (".link { color: %(dim)s; text-decoration: underline dotted; "
                     "text-decoration-color: %(dim)s; text-underline-offset: 2px; }")


def to_html(md, title=None, meta=None):
    """A complete, dark HTML document for a WKWebView hover panel.

    title and meta (e.g. "Dreiling_Clip, written 4 min ago") are plain text
    shown small at the top. Everything from the message is escaped at the leaf
    (see module docstring); links are allowlisted by scheme and get
    rel="noopener"; a CSP meta tag forbids all scripts.
    """
    top = ""
    if title or meta:
        top = '<header class="top">%s%s</header>\n' % (
            '<div class="title">%s</div>' % _esc(title) if title else "",
            '<div class="meta">%s</div>' % _esc(meta) if meta else "")
    body = _html_blocks(parse_blocks(_lines(md)))
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta http-equiv="Content-Security-Policy" content="%s">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n<main class="doc">\n%s'
            '<div class="body">\n%s\n</div>\n</main>\n</body>\n</html>\n'
            % (_esc(_CSP), _esc(title or "Message"), _css(), top, body))


# ---------------------------------------------------------------------------
# HTML auditing (used by --selftest and --corpus)
# ---------------------------------------------------------------------------
_ALLOWED_TAGS = {
    "html": {"lang"}, "head": set(), "meta": {"charset", "http-equiv", "content", "name"},
    "title": set(), "style": set(), "body": set(), "main": {"class"}, "header": {"class"},
    "div": {"class"}, "span": {"class"}, "p": set(), "br": set(), "hr": set(),
    "h1": set(), "h2": set(), "h3": set(), "h4": set(), "h5": set(), "h6": set(),
    "pre": set(), "code": set(), "blockquote": set(), "ul": set(), "ol": {"start"},
    "li": set(), "table": set(), "thead": set(), "tbody": set(), "tr": set(),
    "th": {"class"}, "td": {"class"}, "strong": set(), "em": set(), "u": set(),
    "mark": set(), "del": set(), "a": {"href", "rel"},
}


def audit_html(doc):
    """Parse doc and return (problems, visible_chunks).

    problems: every tag or attribute not on the allowlist, any href whose
    scheme is not allowlisted, a missing or weak CSP.
    visible_chunks: [(text, inside_code, parent_tag, starts_line)] for every text
    node in <body>; starts_line is True when nothing but a block start or <br>
    precedes it on its visual line.
    """
    from html.parser import HTMLParser

    problems = []
    chunks = []

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack = []
            self.csp = None
            self.at_line = True

        def handle_starttag(self, tag, attrs):
            allowed = _ALLOWED_TAGS.get(tag)
            if allowed is None:
                problems.append("tag <%s>" % tag)
            else:
                for name, val in attrs:
                    if name not in allowed:
                        problems.append("attribute %s on <%s>" % (name, tag))
                    if tag == "a" and name == "href" and not _safe_url(val or ""):
                        problems.append("unsafe href %r" % val)
                    if tag == "a" and name == "rel" and val != "noopener":
                        problems.append("rel=%r" % val)
                    if tag == "meta" and name == "http-equiv" and (val or "").lower() == "content-security-policy":
                        self.csp = dict(attrs).get("content", "")
            if tag not in ("br", "hr", "meta"):
                self.stack.append(tag)
            self.at_line = tag in _BLOCK_TAGS or tag in ("br", "hr", "ul", "ol", "tr")

        def handle_endtag(self, tag):
            if tag in _BLOCK_TAGS or tag in ("ul", "ol", "tr", "table"):
                self.at_line = True
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass

        def handle_data(self, data):
            if "body" in self.stack and "style" not in self.stack:
                chunks.append((data, "code" in self.stack or "pre" in self.stack,
                               self.stack[-1] if self.stack else "", self.at_line))
            if data.strip():
                self.at_line = False

    p = P()
    p.feed(doc)
    p.close()
    if not p.csp or "script-src 'none'" not in p.csp or "default-src 'none'" not in p.csp:
        problems.append("CSP missing or allows scripts: %r" % p.csp)
    return problems, chunks


_RAW_MARKERS = [
    # __ and _x_ skip path underscores (after "/", or before "./" + a letter), which
    # _literal_run keeps literal on purpose: /__pycache__/, __init__.py
    ("**", re.compile(r"\*\*")), ("__", re.compile(r"(?<![\w/])__(?![./]\w)|(?<!/)__(?!\w|[./]\w)")),
    ("==", re.compile(r"(?<![\w\s=])==|(?<!\w)==(?=[^\s=])")),
    ("++", re.compile(r"(?<![\w\s+])\+\+|(?<!\w)\+\+(?=[^\s+])")),
    ("~~", re.compile(r"~~")),
    ("`", re.compile(r"`")), ("](", re.compile(r"\]\(")),
    ("*x*", re.compile(r"(?<![\w*\\])\*(?=[^\s*])[^*\n]*?(?<=[^\s*])\*(?![\w*])")),
    ("_x_", re.compile(r"(?<![\w\\/])_(?=[^\s_])[^_\n]*?(?<=[^\s_])_(?!\w|[./]\w)")),
]
_BLOCK_TAGS = {"p", "li", "td", "th", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "div"}
_RAW_LINE_START = re.compile(r"^(#{1,6} |> |[-*+] |\d{1,3}[.)] |\|.*\||```|~~~)")
# A table cell or a heading may start with "1. " as its author wrote it ("## 1. Setup").
_LINE_START_EXEMPT = ("td", "th", "h1", "h2", "h3", "h4", "h5", "h6")


def raw_markers(doc):
    """Supported markers still visible as literal characters in rendered HTML
    (text outside code). Line-start markers (# > - 1. | ```) count only at a real
    line start (first text of a block, or right after <br>) directly inside a
    block element other than a table cell or heading: "**1. Done.**" is bold
    text starting with "1.", "| 1. Row |" is a numbered cell and "## 1. Setup"
    a numbered heading, all as their authors wrote.
    Returns [(marker, context)]."""
    _, chunks = audit_html(doc)
    found = []
    for text, in_code, parent, starts_line in chunks:
        if in_code:
            continue
        for name, rx in _RAW_MARKERS:
            for m in rx.finditer(text):
                a = max(0, m.start() - 30)
                found.append((name, text[a:m.end() + 30].replace("\n", " ")))
        if not starts_line or parent not in _BLOCK_TAGS or parent in _LINE_START_EXEMPT:
            continue
        first = text.strip().split("\n")[0]
        if _RAW_LINE_START.match(first):
            found.append(("line-start", first[:60]))
    return found


# ---------------------------------------------------------------------------
# Self test: every planted control must PASS on this code and must FAIL when
# the feature it guards is sabotaged (so no control is a tautology).
# ---------------------------------------------------------------------------
_EMOJI_SEQ = "\U0001F44D\U0001F3FD"                                   # thumbs up, medium skin
_FAMILY = "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"  # ZWJ family of four


def _tag_count(doc, tag):
    return len(re.findall(r"<%s[\s>]" % tag, doc))


def _controls():
    C = []

    def control(name, sabotage):
        def deco(fn):
            C.append((name, fn, sabotage))
            return fn
        return deco

    @control("nested **bold *italic* bold**", {"_emphasis": lambda toks: _finalize(toks)})
    def _():
        h = to_html("**bold *italic* bold**")
        v = visible_text("**bold *italic* bold**")
        return ("<strong>bold <em>italic</em> bold</strong>" in h and v == "bold italic bold",
                "visible=%r" % v)

    @control("==highlight== mid-sentence", {"_PAIR_CHARS": "~+"})
    def _():
        md = "The ==one thing== to check."
        h = to_html(md)
        return ("The <mark>one thing</mark> to check." in h and visible_text(md) == "The one thing to check.",
                "visible=%r" % visible_text(md))

    @control("++underline++", {"_PAIR_CHARS": "~="})
    def _():
        md = "Read ++this part++ first."
        h = to_html(md)
        return "<u>this part</u>" in h and visible_text(md) == "Read this part first.", visible_text(md)

    @control("emoji skin tone + ZWJ family byte-for-byte",
             {"_esc": lambda s: html.escape(s, quote=True).encode("ascii", "xmlcharrefreplace").decode()})
    def _():
        md = "Shipped **%s** and ==%s== ok" % (_EMOJI_SEQ, _FAMILY)
        want = [_EMOJI_SEQ.encode("utf-8"), _FAMILY.encode("utf-8")]
        h = to_html(md).encode("utf-8")
        v = visible_text(md).encode("utf-8")
        ok = all(w in h and w in v for w in want)
        detail = "html+visible"
        try:
            a = str(inline_attributed(md).string()).encode("utf-8")
            ok = ok and all(w in a for w in want)
            detail += "+attributed"
        except ImportError:
            detail += " (AppKit missing, attributed not checked)"
        return ok, detail

    @control("`code with **stars**` is not bolded", {"_CODE_TICK": "\x00"})
    def _():
        h = to_html("Run `code with **stars**` now")
        return "<code>code with **stars**</code>" in h and "<strong>" not in h, ""

    @control("<script> and <img onerror> escaped in to_html", {"_esc": lambda s: s})
    def _():
        md = "<script>alert(1)</script> and <img src=x onerror=alert(1)> **x**"
        h = to_html(md, title="<img src=x onerror=alert(1)>", meta="</style><script>alert(1)</script>")
        probs, _c = audit_html(h)
        ok = ("&lt;script&gt;alert(1)&lt;/script&gt;" in h and "<script" not in h.lower()
              and "<img" not in h.lower() and "</style><script" not in h and not probs)
        return ok, "; ".join(probs)

    @control("3-column pipe table -> <table> with 3 <th>", {"_table_at": lambda lines, i: None})
    def _():
        md = "Before:\n| Lane | Status | Files |\n|---|:-:|--:|\n| Clip | **done** | 3 |\n| EQ | wait | 12 |"
        h = to_html(md)
        return (_tag_count(h, "table") == 1 and _tag_count(h, "th") == 3 and _tag_count(h, "td") == 6
                and '<td class="r">12</td>' in h), "th=%d td=%d" % (_tag_count(h, "th"), _tag_count(h, "td"))

    @control("fenced code keeps its indentation", {"_fence_body_line": lambda line, ind: line.strip()})
    def _():
        code = "def f(x):\n    if x:\n        return '<b>'\n\treturn 2"
        h = to_html("Here:\n\n```python\n%s\n```\nafter" % code)
        return "<pre><code>%s</code></pre>" % html.escape(code) in h, ""

    @control('visible_len("**ab** ==c==") == 4', {"_emphasis": lambda toks: _finalize(toks)})
    def _():
        n = visible_len("**ab** ==c==")
        return n == 4, "got %d" % n

    @control("visible_len counts what a reader sees: a ZWJ family is 1, not 7", {"grapheme_len": len})
    def _():
        plain = {
            "ZWJ family of four": (_FAMILY, 1),
            "thumbs up with a skin tone": (_EMOJI_SEQ, 1),
            "one flag": ("\U0001F1FA\U0001F1F8", 1),
            "two flags in a row": ("\U0001F1FA\U0001F1F8\U0001F1EC\U0001F1E7", 2),
            "keycap 1": ("1️⃣", 1),
            "e with a combining accent": ("é", 1),
            "Hangul syllable written in parts": ("각", 1),
            "tag sequence flag": ("\U0001F3F4" + "".join(chr(c) for c in (0xE0067, 0xE0062, 0xE0065,
                                                                          0xE006E, 0xE0067, 0xE007F)), 1),
            "four pictures joined by ZWJ": ("\U0001F469‍❤️‍\U0001F48B‍\U0001F468", 1),
            "heart with a variation selector": ("❤️", 1),
            "plain letters and a space": ("a b", 3),
        }
        bad = ["%s: %d not %d" % (n, visible_len(s), w) for n, (s, w) in plain.items() if visible_len(s) != w]
        if visible_len("**Shipped %s** now" % _FAMILY) != 13:
            bad.append("a family inside bold text")
        # The headline limit is what a reader counts: 49 letters and one family emoji is 50, not 56.
        head = opening_line("Waiting on you: " + "x" * 33 + _FAMILY)
        if not (head["visible_len"] == 50 and head["ok"]):
            bad.append("headline %d, ok %s" % (head["visible_len"], head["ok"]))
        ref = "Foundation not checked"
        try:                                  # calibration: Apple's own composed character sequences
            import Foundation
            off = []
            for n, (s, _w) in plain.items():
                ns = Foundation.NSString.stringWithString_(s)
                ns = ns.nsstring() if hasattr(ns, "nsstring") else ns
                i = c = 0
                while i < ns.length():
                    r = ns.rangeOfComposedCharacterSequenceAtIndex_(i)
                    i, c = r[0] + r[1], c + 1
                if c != grapheme_len(s):
                    off.append("%s: mine %d, Foundation %d" % (n, grapheme_len(s), c))
            bad += off
            ref = "agrees with Foundation on all %d" % len(plain) if not off else "; ".join(off)
        except ImportError:
            pass
        return not bad, "; ".join(bad) if bad else ref

    @control("opening_line: 200 visible ok, 201 not", {"visible_text": lambda md: md})
    def _():
        l200 = "**Done:** " + "w" * 193 + "."        # raw 204 chars, visible 200
        l201 = "**Done:** " + "w" * 194 + "."
        a, b = opening_line("\n\n" + l200 + "\nmore"), opening_line(l201)
        return (a["ok"] and a["visible_len"] == 200 and not b["ok"] and b["visible_len"] == 201
                and b["complete"] and a["line"] == l200), "200:%r 201:%r" % (a["visible_len"], b["visible_len"])

    @control('"Summary:" is not complete', {"_TERMINALS": ".!?:"})
    def _():
        o = opening_line("Summary:\n- a")
        o2 = opening_line("Everything is ready. Summary:")
        return not o["complete"] and not o["ok"] and not o2["complete"], ""

    @control("a line ending in an emoji is complete", {"_ends_with_emoji": lambda s: False})
    def _():
        lines = ["Shipped it \U0001F389", "All good " + _EMOJI_SEQ, "Family day " + _FAMILY,
                 "**Green light** \u2705", "Keycap 1\ufe0f\u20e3"]
        res = [opening_line(x)["complete"] for x in lines]
        return all(res), str(res)

    # extra controls beyond the brief
    @control("javascript:/data: links get no href; https gets rel=noopener",
             {"_safe_url": lambda u: True})
    def _():
        h = to_html("[a](javascript:alert(1)) [b](data:text/html,x) [c](https://apple.com/?a=1&b=\"2\")")
        probs, _c = audit_html(h)
        ok = ("javascript:" not in h.split("<body>")[1].split('class="link">a')[0]
              and 'href="javascript' not in h and 'href="data' not in h
              and '<a href="https://apple.com/?a=1&amp;b=&quot;2&quot;" rel="noopener">c</a>' in h
              and not probs)
        return ok, "; ".join(probs)

    @control("CSP meta forbids scripts", {"_CSP": "default-src *"})
    def _():
        probs, _c = audit_html(to_html("x"))
        return not probs, "; ".join(probs)

    @control("snake_case, ~30 GiB, C++, a == b stay literal", {"_UNDERSCORE_STRICT": False})
    def _():
        md = "use snake_case_name and ~30 GiB, C++ and C++, a == b"
        return visible_text(md) == md and "<em>" not in to_html(md), visible_text(md)

    @control("heading, nested list, ordered start, quote", {"_LIST_RE": re.compile(r"(?!)")})
    def _():
        md = "# Title\nIntro:\n- one\n  - nested **b**\n- two\n\n3. third\n4. fourth\n\n> quoted *it*"
        h = re.sub(r"\n(?=<)", "", to_html(md))
        ok = ("<h1>Title</h1>" in h and "<li>one<ul><li>nested <strong>b</strong></li></ul></li>" in h
              and '<ol start="3">' in h and "<blockquote><p>quoted <em>it</em></p></blockquote>" in h)
        return ok, ""

    @control("hostile shapes: no exception, each under 0.25 s", {"_MAX_NEST": 10 ** 6})
    def _():
        import time
        shapes = ["a* " * 3000, "[a " * 3000, "[a](" * 3000, "` `` " * 1500, "_a " * 3000,
                  ">" * 3000 + " x", "*" * 3000 + "a" + "*" * 3000, "**a " * 1500 + "a** " * 1500,
                  "\n".join(" " * (2 * i) + "- a" for i in range(600)),
                  "[" * 3000 + "a" + "]" * 3000 + "(https://x)", "|" * 3000 + "\n" + "|-" * 1500]
        worst = 0.0
        for md in shapes:
            t0 = time.time()
            to_html(md)
            visible_len(md)
            opening_line(md)
            worst = max(worst, time.time() - t0)
        return worst < 0.25, "slowest %.3f s" % worst

    @control("cell string == visible_text (one engine)", {"_runs": lambda md: [(md, _EMPTY)]})
    def _():
        samples = {"**1. The drive is fine.**": "1. The drive is fine.",
                   "- item with `code` and [link](https://x.y)": "\u2022 item with code and link",
                   "## Heading ==hi==": "Heading hi", "> quote ~~old~~ new": "quote old new",
                   "Plain " + _FAMILY: "Plain " + _FAMILY}
        try:
            bad = [s for s, want in samples.items()
                   if str(inline_attributed(s).string()) != visible_text(s) or visible_text(s) != want]
        except ImportError:
            return True, "AppKit missing, skipped"
        return not bad, "mismatch: %r" % bad

    # ---- controls added with the fixes for the independent checker's findings ----
    def slow_finalize(toks):          # the old version: repeated string +=
        out = []
        for t in toks:
            if t[0] == "delim":
                if t[2] <= 0:
                    continue
                t = ["text", t[1] * t[2]]
            if t[0] == "text" and out and out[-1][0] == "text":
                out[-1] = ["text", out[-1][1] + t[1]]
            else:
                out.append(t)
        return out

    def slice_emphasis(toks):         # the old version: toks[a:b] = [node] shifts the tail
        bottom, i = {}, 0
        while i < len(toks):
            t = toks[i]
            if t[0] != "delim" or not t[4] or t[2] <= 0:
                i += 1
                continue
            ch, key, opener, j = t[1], (t[1], t[3], t[5] % 3), None, i - 1
            while j >= bottom.get(key, 0):
                o = toks[j]
                if o[0] == "delim" and o[1] == ch and o[3] and o[2] > 0:
                    if ch in _EMPH_CHARS:
                        if ((o[4] or t[3]) and (o[5] + t[5]) % 3 == 0
                                and not (o[5] % 3 == 0 and t[5] % 3 == 0)):
                            j -= 1
                            continue
                    elif o[2] < 2 or t[2] < 2:
                        j -= 1
                        continue
                    opener = j
                    break
                j -= 1
            if opener is None:
                bottom[key] = i
                i += 1
                continue
            inner, o = toks[opener + 1:i], toks[opener]
            use = 2 if (ch not in _EMPH_CHARS or (o[2] >= 2 and t[2] >= 2)) else 1
            kind = _PAIR_KIND.get(ch) or ("strong" if use == 2 else "em")
            o[2] -= use
            t[2] -= use
            toks[opener + 1:i] = [[kind, _finalize(inner), 1]]
            for k2, v in bottom.items():
                if v > opener + 1:
                    bottom[k2] = opener + 1
            i = opener + 2
        return _finalize(toks)

    @control("arithmetic keeps its *: 2*3*4, k*1000, pi*f", {"_STAR_MATH_LITERAL": False})
    def _():
        maths = ["2*3*4 = 24", "44100*2*60 samples", "|k*1000 - n*48000|",
                 "20*log10(cos(pi*fnorm/n))", "= 7+300*0+200, and `b 1725` = 897+4*207."]
        bad = [m for m in maths if "<em>" in to_html(m) or visible_text(m) != m.replace("`", "")]
        still = (visible_text("a *b* c") == "a b c" and "<em>b</em>" in to_html("a *b* c")
                 and "Pi<strong>zz</strong>" in to_html("Pi**zz**")
                 and "<em><strong>bi</strong></em>" in to_html("***bi***"))
        return not bad and still, "changed: %r" % bad

    @control("unmatched markers: 8000-line paragraph under 0.2 s", {"_finalize": slow_finalize})
    def _():
        import time
        shapes = ["\n".join(["rm *.tmp in _build dir and ==x"] * 8000),
                  "\n".join(["12:00:01 *WARN _flag set ++retry"] * 8000), "*a _b " * 30000]
        worst = 0.0
        for md in shapes:
            for fn in (to_html, visible_text, opening_line):
                t0 = time.time()
                fn(md)
                worst = max(worst, time.time() - t0)
        return worst < 0.2, "slowest %.3f s" % worst

    @control("matched pairs scale linearly (8x input < 14x time)", {"_emphasis": slice_emphasis})
    def _():
        import time

        def best(md):
            ts = []
            for _k in range(3):
                t0 = time.time()
                parse_inline(md)
                ts.append(time.time() - t0)
            return min(ts)
        small, big = best("**a *b* c** " * 5000), best("**a *b* c** " * 40000)
        return big < 14 * small and big < 1.0, "5000: %.3f s, 40000: %.3f s, ratio %.1f" % (
            small, big, big / max(small, 1e-9))

    @control("path underscores stay: __init__.py, /__pycache__/", {"_PATH_UNDERSCORE_LITERAL": False})
    def _():
        paths = ["__init__.py and edit __init__.py now", "/tmp/__pycache__/x.pyc",
                 "https://x.com/_private_/y", "~/Desktop/_archive_/old",
                 "https://raw.githubusercontent.com/h/f/master/__init__.py"]
        bad = [p for p in paths if visible_text(p) != p]
        still = ("<strong>bold</strong>" in to_html("__bold__") and "<em>italic</em>." in to_html("_italic_.")
                 and "<em>Align SPL...</em> feature" in to_html("_Align SPL..._ feature"))
        return not bad and still and not raw_markers(to_html(paths[1])), "changed: %r" % bad

    @control("opening_line skips fence/rule lines; code is never ok", {"_OPENING_SKIPS_EMPTY": False})
    def _():
        a = opening_line("```python\nprint(1)\n```\nDone.")
        b = opening_line("```\nAll done.\n```\nx")
        c = opening_line("---\nDone.")
        d = opening_line("#\n>\n***\n**Done.**")
        ok = (a["line"] == "print(1)" and a["code"] and a["visible_len"] == 8 and not a["complete"]
              and b["line"] == "All done." and not b["complete"] and not b["ok"]
              and c["line"] == "Done." and c["ok"] and not c["code"]
              and d["line"] == "**Done.**" and d["ok"])
        return ok, "%r | %r | %r" % (a, b, c)

    @control('"text |" then "---" is a sentence and a rule', {"_TABLE_RULE_NEEDS_PIPE": False})
    def _():
        h1 = to_html("Use `a|b` to split.\n---\nNext.")
        h2 = to_html("Status: done |\n---")
        h3 = to_html("| x |\n|---|\n| 1 |")
        ok = ("<table>" not in h1 and "<hr>" in h1 and "<p>Use <code>a|b</code> to split.</p>" in h1
              and "<table>" not in h2 and "<hr>" in h2 and _tag_count(h3, "td") == 1)
        return ok, ""

    @control("C++ and j++ never close an underline", {"_PLUS_CODE_GUARD": False})
    def _():
        md = ["Use ++count in C++", "++i and j++", "i++ and ++j"]
        bad = [m for m in md if visible_text(m) != m or "<u>" in to_html(m)]
        still = "<u>this part</u>" in to_html("Read ++this part++ first.")
        return not bad and still, "changed: %r" % bad

    @control("a one-character ++b++ underlines; C++ and j++ still do not", {"_ONE_CHAR_UNDERLINE": False})
    def _():
        h = to_html("a ++b++ c")
        at_edges = ["<u>b</u>" in to_html(m) for m in ("++b++ first", "last ++b++", "(++b++)", "a ++b++, c")]
        code = [m for m in ("Use ++count in C++", "++i and j++", "i++ and ++j", "x ++i++j")
                if visible_text(m) != m or "<u>" in to_html(m)]
        return ("<u>b</u>" in h and visible_text("a ++b++ c") == "a b c" and all(at_edges) and not code,
                "html=%r edges=%r code changed=%r" % (h[:80], at_edges, code))

    @control("raw_markers: numbered heading is not a leftover", {"_LINE_START_EXEMPT": ("td", "th")})
    def _():
        clean = raw_markers(to_html("## 1. himalaya v2.1.0\n### 2. Setup"))
        caught = raw_markers(to_html("\\# not a heading"))
        return not clean and caught == [("line-start", "# not a heading")], "clean=%r caught=%r" % (clean, caught)

    @control('ellipsis: "..." and "\\u2026" both not complete', {"_ELLIPSES": ()})
    def _():
        r = [is_complete(x) for x in ("Working on it...", "Working on it…", "(still going…)")]
        return r == [False, False, False] and is_complete("Done."), str(r)

    def emoji_before_closers(visible):   # the old order: emoji test before closers are stripped
        s = (visible or "").rstrip()
        if not s:
            return False
        if _ends_with_emoji(s):
            return True
        k = len(s)
        while k and s[k - 1] in _CLOSERS:
            k -= 1
        return bool(k) and s[k - 1] in _TERMINALS

    @control("emoji before a closer is complete: (done \U0001F389)", {"is_complete": emoji_before_closers})
    def _():
        r = [is_complete(x) for x in ("(done \U0001F389)", "\"shipped ✅\"", "(done.)")]
        return all(r), str(r)

    @control("any base + VS16 is emoji: ‼️ ⁉️ ↔️", {"_VS16_ANY_BASE": False})
    def _():
        r = [is_complete(x) for x in ("Done ‼️", "Done ⁉️", "Swap ↔️",
                                      "Careful ⚠️")]
        return all(r), str(r)

    @control("text-style symbols are not emoji: ✓ ⌘ ➜", {"_EMOJI_RANGES": (
            (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2300, 0x23FF), (0x2B00, 0x2BFF))})
    def _():
        r = [is_complete(x) for x in ("Next ✓", "Press ⌘", "Next ➜", "Done ✔")]
        yes = [is_complete(x) for x in ("Time ⌚", "Hot ☕", "Done ✅", "Star ⭐")]
        return not any(r) and all(yes), "text-style %r, emoji %r" % (r, yes)

    @control("cell folds \\r \\n tab U+2028 to spaces", {"fold_line": lambda s: (s or "").strip()})
    def _():
        want = {"a\r\nb": "a b", "a\rb": "a b", "tab\there": "tab here", "x y": "x y",
                "**b**\r\n  _i_": "b i"}
        bad = [s for s, w in want.items() if visible_text(fold_line(s)) != w]
        try:
            bad += [s for s, w in want.items() if str(inline_attributed(s).string()) != w]
        except ImportError:
            pass
        return not bad, "bad: %r" % bad

    @control("lone surrogate: every output encodes as UTF-8", {"_desurrogate": lambda s: s or ""})
    def _():
        md = "bad \ud83d end **b\udc00**"
        outs = [to_html(md, title="t\udc00", meta="m\ud800"), visible_text(md), opening_line(md)["line"],
                fold_line(md)]
        try:
            outs.append(str(inline_attributed(md).string()))
        except ImportError:
            pass
        bad = []
        for k, s in enumerate(outs):
            try:
                s.encode("utf-8")
            except UnicodeEncodeError:
                bad.append(k)
        return not bad and "�" in outs[1], "not encodable: %r" % bad

    @control("100. inside a paragraph does not start a list", {"_interrupts_para": lambda l: _starts_block(l)})
    def _():
        h = to_html("The count was\n100. That is high.")
        still = '<ol start="3">' not in to_html("Intro:\n- a") and "<ol>" in to_html("Steps:\n1. one\n2. two")
        return "<ol" not in h and "100. That is high." in visible_text("The count was\n100. That is high.") \
            and still, h.split("<body>")[1][:120]

    @control("a numbered list resumes after a lead-in line", {"_continues_list": lambda line, n: False})
    def _():
        h = re.sub(r"\n(?=<)", "", to_html("1. a\n2. b\n\n**Worth knowing:**\n3. c\n4. d"))
        return ('<p><strong>Worth knowing:</strong></p><ol start="3"><li>c</li><li>d</li></ol>' in h,
                h.split("<body>")[1][:200])

    @control("table cell: `x \\| y` shows x | y", {"_CELL_CODE_UNPIPE": False})
    def _():
        h = to_html("| cmd | note |\n|---|---|\n| `x \\| y` | in code |\n| a \\| b | plain |")
        return "<td><code>x | y</code></td>" in h and "<td>a | b</td>" in h, ""

    @control("zero-width-only line is skipped by opening_line", {"_INVISIBLE": ""})
    def _():
        a = opening_line("​\nDone.")
        b = opening_line("​⁠ Done.​")
        return (a["line"] == "Done." and a["visible_len"] == 5 and b["line"] == "Done."
                and b["visible_len"] == 5), "%r %r" % (a, b)

    @control("leading BOM is dropped", {"_BOM": ""})
    def _():
        md = "﻿Done."
        return (visible_text(md) == "Done." and visible_len(md) == 5 and "﻿" not in to_html(md)
                and opening_line(md)["visible_len"] == 5), repr(visible_text(md))

    @control("blocked link is dim and dotted, not like a working one", {"_BLOCKED_LINK_CSS": ".link { }"})
    def _():
        h = to_html("[bad](javascript:alert(1)) and [good](https://x.y)")
        css = h.split("<style>")[1].split("</style>")[0]
        rule = re.search(r"^\.link \{[^}]*\}", css, re.M)
        ok = ('<span class="link">bad</span>' in h and '<a href="https://x.y" rel="noopener">good</a>' in h
              and rule is not None and "dotted" in rule.group(0) and _css_color("dim") in rule.group(0)
              and "dotted" not in re.search(r"^a \{[^}]*\}", css, re.M).group(0))
        try:
            import AppKit as A
            s = inline_attributed("[bad](javascript:x) [good](https://x.y)")
            u0 = s.attributesAtIndex_effectiveRange_(0, None)[0][A.NSUnderlineStyleAttributeName]
            u1 = s.attributesAtIndex_effectiveRange_(4, None)[0][A.NSUnderlineStyleAttributeName]
            ok = ok and u0 == A.NSUnderlineStyleSingle | A.NSUnderlineStylePatternDot \
                and u1 == A.NSUnderlineStyleSingle
        except ImportError:
            pass
        return ok, rule.group(0) if rule else "no .link rule"

    return C


def selftest(verbose=True):
    g = globals()
    failures = 0
    lines = []
    for i, (name, fn, sabotage) in enumerate(_controls(), 1):
        try:
            ok, detail = fn()
        except Exception as e:           # a crash is a failure, reported
            ok, detail = False, "EXCEPTION %r" % e
        saved = {k: g[k] for k in sabotage}
        g.update(sabotage)
        try:
            try:
                s_ok, _d = fn()
            except Exception:
                s_ok = False
        finally:
            g.update(saved)
        can_fail = not s_ok
        good = ok and can_fail
        failures += not good
        lines.append("%s %2d %-52s %s%s" % (
            "PASS" if good else "FAIL", i, name,
            "sabotage(%s) makes it fail" % ",".join(sabotage) if can_fail else "SABOTAGE DID NOT FAIL IT",
            "" if ok else "   detail: %s" % detail))
    lines.append("%d controls, %d failed" % (len(_controls()), failures))
    if verbose:
        print("\n".join(lines))
    return failures == 0, "\n".join(lines)


# ---------------------------------------------------------------------------
# Real corpus: the latest message of every live session (read only)
# ---------------------------------------------------------------------------
def live_messages():
    """[(pid, session_id, name, iso_timestamp, text)] for every live session's
    latest assistant entry with a text block. Reads only."""
    import glob
    import json
    import os
    home = os.path.expanduser("~")
    out = []
    for f in sorted(glob.glob(os.path.join(home, ".claude/sessions/*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            pid, sid = int(d.get("pid")), d.get("sessionId")
            os.kill(pid, 0)
        except Exception:
            continue
        hits = glob.glob(os.path.join(glob.escape(os.path.join(home, ".claude/projects")), "*", "%s.jsonl" % sid))
        if not hits:
            continue
        last, ts = None, None
        with open(hits[0], encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"assistant"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                c = (e.get("message") or {}).get("content")
                if not isinstance(c, list):
                    continue
                texts = [b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip()]
                if texts:
                    last, ts = "\n\n".join(texts), e.get("timestamp")
        if last is not None:
            out.append((pid, sid, d.get("name") or sid[:8], ts, last))
    return out


def _ago(ts):
    import datetime
    try:
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        m = int((datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() // 60)
    except Exception:
        return "written earlier"
    if m < 1:
        return "written just now"
    if m < 90:
        return "written %d min ago" % m
    return "written %d h ago" % (m // 60)


def corpus_report(out_dir=None, verbose=True):
    import os
    msgs = live_messages()
    rows, ok_n, exc, raw_all, audit_all, mismatch = [], 0, [], [], [], []
    for pid, sid, name, ts, text in msgs:
        try:
            ol = opening_line(text)
            vt = visible_text(text)
            doc = to_html(text, title=name, meta="pid %d, %s" % (pid, _ago(ts)))
            probs, _c = audit_html(doc)
            raw = raw_markers(doc)
            try:
                cell = str(inline_attributed(ol["line"]).string())
                if cell != visible_text(fold_line(ol["line"])) or grapheme_len(cell) != ol["visible_len"]:
                    mismatch.append(pid)
            except ImportError:
                cell = None
            if out_dir:
                with open(os.path.join(out_dir, "richtext_%d.html" % pid), "w", encoding="utf-8") as fh:
                    fh.write(doc)
        except Exception as e:
            import traceback
            exc.append((pid, repr(e), traceback.format_exc()))
            continue
        ok_n += ol["ok"]
        audit_all += [(pid, p) for p in probs]
        raw_all += [(pid, m, ctx) for m, ctx in raw]
        why = "ok" if ol["ok"] else ("incomplete" if not ol["complete"] else "") + \
            (" over %d" % LIMIT if ol["visible_len"] > LIMIT else "")
        rows.append("%6d  %-3s %4d  %-18s %s" % (pid, "ok" if ol["ok"] else "NO", ol["visible_len"],
                                                why.strip(), ol["line"][:90]))
    lines = ["pid     ok  vlen  why                opening line (first 90 raw chars)"] + rows
    lines.append("")
    lines.append("sessions: %d   opening lines ok: %d/%d   exceptions: %d   audit problems: %d   "
                 "raw markers: %d   cell/visible mismatches: %d"
                 % (len(msgs), ok_n, len(rows), len(exc), len(audit_all), len(raw_all), len(mismatch)))
    for pid, e, tb in exc:
        lines.append("EXCEPTION pid %d: %s\n%s" % (pid, e, tb))
    for pid, p in audit_all:
        lines.append("AUDIT pid %d: %s" % (pid, p))
    for pid, m, ctx in raw_all:
        lines.append("RAW pid %d %s: %r" % (pid, m, ctx))
    report = "\n".join(lines)
    if verbose:
        print(report)
    return {"sessions": len(msgs), "ok": ok_n, "exceptions": exc, "audit": audit_all,
            "raw": raw_all, "mismatch": mismatch, "report": report}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv):
    import os
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--selftest":
        ok, _ = selftest()
        return 0 if ok else 1
    if argv[0] == "--render" and len(argv) >= 2:
        src = argv[1]
        title = meta = None
        rest = argv[2:]
        while rest:
            if rest[0] == "--title" and len(rest) > 1:
                title, rest = rest[1], rest[2:]
            elif rest[0] == "--meta" and len(rest) > 1:
                meta, rest = rest[1], rest[2:]
            else:
                print("unknown argument %r" % rest[0], file=sys.stderr)
                return 2
        with open(src, encoding="utf-8") as fh:
            md = fh.read()
        dst = os.path.splitext(src)[0] + ".html"
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(to_html(md, title=title or os.path.basename(src), meta=meta))
        print(dst)
        return 0
    if argv[0] == "--corpus":
        out = argv[2] if len(argv) >= 3 and argv[1] == "--out" else None
        r = corpus_report(out_dir=out)
        return 1 if r["exceptions"] or r["audit"] else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
