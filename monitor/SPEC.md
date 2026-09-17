# Agents.app: the one spec (10 Sep 2026)

Every line below traces to Mason's own words, quoted in section 0. The build team works from this file; a change to
the product changes this file first. The coordinator keeps it.

## 0. His words, in order
1. "i want to see title of conversation, short description (200 character max), amount of time spent on task total,
   # of tasks currently running, # of tasks being run" / "in a table. thats the entire app"
2. "then underneath that table i want to see a giant scrollable list of tasks that are waiting on me. Yellow if it
   requires more than me just reading and making a decision."
3. "and you and I are gonna use the app to monitor what all the other agents are doing live"
4. "then i want all the individual agents to be able to check this list before they make important decisions... an
   alarm that can be set by an agent if it thinks it needs the help of all the other agents. And an individual agent
   can check on the status of the agents for just basic common sense communication if needed."
5. "the 200 character description is a brief description that in its entirety fits within 200 characters. the rest of
   the message can follow, but you only get 200 characters for the title."
6. "i want to hover over an items description to see its entire description clearly. I want the descriptions to use
   italics, underlines, emojis, bold letters, highlights, anything it needs to convey its message to me and you
   simultaneously as effectively as possible."
7. "i want to be able to rename workflows in the app and resize column widths and sorting tools and more options for
   options to sort the conversations by maybe outstanding decisions? Longest combined time waited for all decisions?"
8. "i want to see seconds ticking too"
9. "do you think it can get the descriptions to 50 characters? like a news headline" (answered yes with a newspaper
   structure; not yet confirmed by him, so it ships as a View menu choice, default Headline)
10. "i want to be able to respond directly to open comments and when i hit enter i want the agent to check and see if
   this was already resolved. I want it to already be checking to begin with... and i want to group related questions
   together across conversations"
11. "then i want a notification, this item has already been resolved: 50 characters to explain" / "still reply? yes, no
   or edit as buttons" / "sleek design for this part please"
14. "i also want to be able to speak directly to the workflow agent in a message bar, and select multiple messages to
    respond to multiple messages at once. And i want to see a readout of storage space somewhere, estimate of storage
    space changes after this task is complete/agents are ran"
13. "see if you were waiting on me to back up my computer you shouldve said that first thing in the headline"
    (so: when an agent waits on him, its headline starts "Waiting on you:"; the app marks those rows with the orange
    accent and sorts them first under "most decisions waiting on you")
12. "maybe let these agents work together?" (read as: the agents behind a group of related questions confer and bring
   him one combined question, or settle it without him)
15. THE PURPOSE, 15 Sep 2026, verbatim: "what im hoping for is a less disconnected network of work done by the team
    (me, you and the other agents) and a more "neural" network so to speak. If the EQ agent finds some crazy technique
    for plugin development, then it needs to 1 know that is a crazy development 2 know to alert the others 3 present
    the others with helpful information 4 the others should give it an honest go and try to use that information....
    This app is trying to encourage all of that. Right now the plugin development happening in paralell across all my
    agents feels disconnected... certain ideas are not getting carried over. I'd like to nip that in the butt now.
    This agent console (new name) is like a twitter/slack for my agents. Maybe i should just get slack and fill it
    with agents for now? idk im open to ideas here"
    (so: the app is renamed THE AGENT CONSOLE; its first job is carrying ideas between agents, in his four steps;
    every feature is judged by whether it helps a finding travel from one lane into another lane's work. Whether to
    use Slack instead, for now, is his open question and is not decided.)
    Same day: "id rather the agents drafting this document right now hear my words then make sure they are written in
    stone somewhere" (this entry is that stone; a change to the product changes this file first).
16. ONE ANSWER, EVERY ASKER, 15 Sep 2026, verbatim: "i want to be knocking two birds out with one stone systematically
    with this app. Tasks waiting for my word across agents should be grouped together by similarity... If i have 3
    agents asking the same question, then i should just have to give one answer one time... understand? if a 4th
    agent stragler comes asking the same question 20 minutes later, maybe he can get the memo when hes ready too.
    you know?"
    (so: asks from different agents that are the same question become ONE item; his one answer goes to every agent
    that asked; his answers are kept, and an agent that asks the same question later is handed the existing answer
    when it asks, instead of the question reaching him again. Grouping by similarity is a requirement, not a
    candidate for removal; how to make it reliable is open.)
17. HIS RULINGS ON THE REDESIGN, 15 Sep 2026, verbatim: "1. yes 2. ok 3. ok 4. ok 5. no they are going to the workflow
    agent (you). you are still the coordinator of all the agents 6. hell no they cant leave 7. yes all at once"
    (so: Phase 0 starts now; grouping is lanes marking related asks with the AI pass as backup, proven by a test of
    three askers plus a late asker; Slack is checked before the screen redesign; "Time spent" and "Tasks run" give way
    to "last real change" and "waiting since"; his replies go to the COORDINATOR, never to per-agent reply files, and
    the coordinator routes them; the hover panel, the eight sort orders and the Headline/Summary menu are KEPT;
    a reply goes out at once and the already-resolved check becomes a hint.)

## 1. The table (top)
Columns, exactly: Conversation | Description | Time spent | Running now | Tasks run.
- Conversation: the cmux sidebar title. RENAME: double-click the title, type, Return. The app runs
  /Applications/cmux.app/Contents/Resources/bin/cmux rename-workspace --workspace <workspaceId> "<title>" (or
  workspace-action --action rename --title). The real sidebar changes. Escape cancels. A "Clear name" item in the row's
  right-click menu runs workspace-action --action clear-name. Verified 10 Sep: the CLI answers from outside cmux with no
  password. Refuse an empty title.
- Description: the agent's latest message, rendered with formatting (section 3). View menu: "Headline (50)" (default)
  or "Summary (200)". Headline = the message's first line when it is a complete statement of at most 50 visible
  characters. Summary = the first line, or the second when the first is the headline, when it is a complete statement
  of at most 200 visible characters. A line over its limit is NEVER cut silently: show its first words and a small
  "over 50" or "over 200" tag, so the rule breaker is visible. HOVER on the cell (0.35 s) opens the panel (section 3).
- Time spent: total working time (definition in monitor_data.py). It TICKS EVERY SECOND while the agent is working
  (registry status busy, or its last transcript entry is not the end of a turn), as "13 h 34 m 07 s"; frozen while it
  waits. Tabular digits so it does not jitter.
- Running now, Tasks run: as built. "?" when unknown, never 0.
- Columns: resizable by dragging, widths and order remembered (NSTableView autosaveName). Right-click the header to
  show or hide two OPTIONAL columns, hidden by default: "Waiting on you" (items of his from that conversation) and
  "Total wait" (their combined waiting time, ticking).
- SORT: click any header to sort, click again to reverse, a small arrow shows which. A "Sort" menu (menu bar and a
  small control above the table) offers: sidebar order (default), time spent, running now, tasks run, most decisions
  waiting on you, longest combined wait, most recently active, alphabetical. The choice is remembered.

## 2. The waiting list (bottom)
- Source: queue.py's build() items, never recounted. Header: "<total> waiting on you. <n> need more than a decision."
- Yellow text when the bucket is not decision (hands, ear, permission, off-machine).
- GROUPS: related items from different conversations sit under one group header naming the topic and the agents in it.
  Grouping is by an agent reading the items (a keyword pass left 25 of 56 ungrouped on 10 Sep), run once each time the
  manifest's sha changes, cached by sha, cheapest capable model, no tools. A group header has one button:
  "Work it out together": it types a request into the LEAD agent's window (the agent that owns the oldest item in the
  group) listing the items and the other agents; the lead confers with them (SendMessage) and replaces the group with
  ONE combined question (options, what is true now, recommendation) or closes what does not need him.
- WAITING TIME per item: queue.py records no start times, so the engine keeps first_seen per item id in its cache,
  backfilled from a date in the item's own record (a status "when" field, a stack cell "OPEN (7 Sep 08:4x)") when one
  parses. Shown as "waiting 3 d 4 h" and ticking; "at least" when only first_seen is known.
- ALREADY CHECKING: continuous free checks mark an item "may be settled" (a small dim tag with the reason) when: his
  answer to it is already in an ANSWERS ledger; a file it names is gone (queue.py world STALE); its CROSS-LANE row is
  closed; or its lane has not re-confirmed it since his last message to that lane.
- REPLY: every item has a reply field. Return sends; Shift-Return makes a new line.
  1. Check, cheapest first: the free checks; then a small separate checker (claude -p with the cheapest capable model
     and NO tools) given the item, the owning lane's status file, and the tail of its conversation, answering exactly
     "OPEN" or "RESOLVED: <at most 50 characters>". Time out at 20 s and treat as OPEN.
  2. RESOLVED: the sleek card (section 4). OPEN: deliver.
  3. DELIVER: append his reply, verbatim, to lab-common/ANSWERS-<date>.md (so his words land even if delivery fails),
     then type into the owning agent's cmux window: "[From the Agents app, about: <item, first 120 chars>] <his reply>
     Before acting, check whether this is already resolved; if it is, say so in one line." via cmux send, then
     cmux send-key Enter. The owner is the item's lane mapped to a session through lab-common/roster.json; stack,
     when-home and listens items go to WORKFLOW.
  4. GUARD: first cmux read-screen that window; NEVER type into a window showing a permission question, a menu, or a
     half-typed prompt of his. Hold the reply in an outbox (shown under the item as "waiting to deliver") and retry
     every 5 s; he can cancel it.

## 3. Formatting (richtext.py)
Source text stays Markdown so agents read it as text; the app renders it: bold, italic, ++underline++, ==highlight==,
code, strike, emoji, and in the hover panel headings, lists, tables, code blocks, quotes, links. The hover panel is an
NSPopover holding a WKWebView with JavaScript OFF, loading richtext.to_html(message, title, meta) where meta is
"<conversation>, written <age> ago". Width about 560 pt, height to fit up to 70 percent of the screen, scrolls. It
stays open while the pointer is over it and closes on exit or Escape.

## 4. The already-resolved card (sleek)
Slides down over the item's reply field (0.18 s ease-out, no bounce; respects Reduce Motion). A rounded dark card,
one hairline border, soft shadow, a small green check glyph, then "Already resolved" in semibold and the at-most-50-
character reason beside it, a dim line "checked by <checker> just now", and three pill buttons on one row:
"Send anyway" (Return), "Don't send" (Escape), "Edit" (E). Edit puts his text back in the field, cursor at the end.
The orange accent is used once, on the focused button. No sounds.

## 5. Alarms
lab-common/monitor/alarm.py writes lab-common/ALARMS.jsonl. Any open alarm shows as a banner across the top of the
window: red, "ALARM from <lane>: <why>", when, who answered; a click opens its full text in the hover panel. The engine
returns open alarms FIRST in its CLI output, so an agent checking the list sees them before anything else.

## 6. For agents (the CLI is how agents "check this list")
python3 lab-common/monitor/monitor_data.py prints alarms, then the table, then the waiting list, as plain text;
--json for machines. Agents run it before important decisions and to check on each other.

## 7. The app itself
- Identity: the Dock and the menu bar must say Agents with its own icon, not Python: set the process name and
  CFBundleName at launch and NSApp.setApplicationIconImage_ with the bundle icon.
- Live: table every 5 s, ticking every 1 s, waiting list every 30 s, grouping when the sha changes. Never flicker,
  never lose his scroll position, selection or an open reply.
- Writes only: its cache folder, the day's ANSWERS ledger (his replies, verbatim), cmux (renames and delivered replies).
- No em dash characters anywhere. Plain words.

## 8. Message bar to the coordinator (his words 14)
A single-line field pinned at the bottom of the window, placeholder "Message the coordinator". Return sends,
Shift-Return adds a line. It records his words verbatim in the day's ANSWERS ledger under "Said from the Agents app",
then delivers to the WORKFLOW window exactly like a reply (section 2 step 3), with the same read-screen guard and
outbox; the prefix is "[From the Agents app]". The field keeps its text until delivery is confirmed.

## 9. Answer several items at once (his words 14)
The waiting list allows multiple selection (Command-click, Shift-click, and a checkbox on each item). With two or more
selected, one reply field docks above the list: "Reply to N items". On Return the app runs the already-resolved check
for every selected item; if any are resolved, ONE card lists them with each reason (at most 50 characters each) and
the same three buttons, which apply to those items only; open items go at once. Delivery groups the items by owning
agent, so each agent gets ONE message listing its items (numbered, each with its first 120 characters) and his reply.
The ledger gets one line per item.

## 10. Storage readout (his words 14)
A slim strip above the waiting list: "Disk  79.4 GiB free  |  floor 30  |  after running work  about 79.0 GiB".
- Free now: statvfs of the data volume, every 5 s.
- After running work: free now minus what each RUNNING run in lab-common/runs.json declared (disk_gb) and has not yet
  used, where used is the growth of its scratch folder since the app first saw that run (never negative); a run with no
  scratch reading counts its full declaration. Labelled an estimate.
- Trend: free-space samples kept in the cache for 2 hours; shown as "falling 0.3 GiB an hour" or "steady", from a
  least-squares line over the last hour, only when there are at least 10 samples.
- Colour: normal above 40 GiB, the orange accent from 30 to 40, red under 30 (the floor). Hover shows each running
  run's name, lane, declared GiB and hours left, and the Time Machine state (tmutil status Running and phase).
- Honest labels: "estimate", never a promise; say "no running work declares disk" when that is the case.

## 11. Decisions after the v2 build (coordinator, 11 Sep 2026 07:1x)
- LAUNCH INSIDE CMUX. cmux admits only processes started inside cmux ("Access denied - only processes started inside
  cmux can connect"; measured by a checker with a double fork). So the app runs from a cmux Dock terminal control named
  "Agents" (command: /opt/homebrew/bin/python3 ".../monitor/agents_app.py"), which is inside cmux's tree. Opened any other
  way (the macOS Dock, Finder), the app detects the refusal ONCE, stops retrying, keeps his typed words (ledger), and shows
  one plain banner: "Open Agents from cmux's right sidebar (the Agents control) so replies and renames can reach your
  agents." No change to cmux's security setting.
- HEADLINE RULE. A news headline has no end punctuation, so a headline is complete when it is at most 50 visible
  characters; only the SUMMARY (at most 200) must end a statement. "Waiting on you: X" is a valid headline.
- TIME SPENT ticks only while the transcript itself is mid-turn (the v2 fix); the registry's busy flag alone does not tick.
- ASKS WITHOUT A REASON. queue.py holds WAITING ON lines that give no "because" out of the count (fence 50). They are still
  asks of him, so the list shows them in a separate collapsed section at the bottom, "Asked of you without saying why (N)",
  dim, never counted, each with its lane, so the lane can be told to justify or drop it.
- "MAY BE SETTLED" uses only the strong checks (his answer already in a ledger, a named file gone, its own CROSS-LANE row
  closed). The silence check ("not re-confirmed since his last message") is dropped: it tagged 16 of 50, mostly because
  every stack item belongs to WORKFLOW, the window he writes to most.
- SAFETY. The text is typed, then the screen is read AGAIN, and Enter is pressed only if the typed text sits in an idle
  prompt box and no question, menu or list is showing; otherwise the typed text is cleared from the box and the reply held.
  Test mode fails CLOSED: if AGENTS_TEST_WORKSPACE is present at all, even empty, every live send and rename is refused.
- THE CARD. Return activates the FOCUSED pill (Tab moves focus; Send anyway is focused first). "Don't send" never discards:
  his text stays in the reply field, editable, and is also kept in the cache as an unsent draft.
