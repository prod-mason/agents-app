# Agents

A native macOS app for watching a room full of Claude Code agents at once.

One table shows every conversation: its title, a one-line headline of what it is doing, total time spent, tasks
running now and tasks run. Under the table is one scrollable list of everything the agents are waiting on you for.
Items that need more than reading and deciding are marked yellow. You can answer items right from the list. Before
your reply is sent, the app checks whether the item was already settled. Related questions from different
conversations are grouped together.

Agents can read the same table and list from the command line before they make a decision, and can raise an alarm
when they need help from all the others.

It was built in a few days for one person's studio setup (a dozen agents working on audio plugins) and is shared
as-is. Take it, change it, sell it, do whatever you want. It is public domain (see UNLICENSE).

## What it expects

- macOS, with Python 3 and PyObjC (`pip install pyobjc`)
- cmux as the terminal, one workspace per agent. The app reads cmux's session file for titles,
  renames workspaces through the cmux command line tool, and types replies into the owning agent's window with
  `cmux send`.
- Claude Code sessions (it reads `~/.claude/sessions` and the conversation transcripts)
- A shared folder that the agents write their status to. The app treats **the folder above `monitor/`** as that
  folder. Each agent writes `status/<name>.json` there, and replies are logged to `ANSWERS-<date>.md` in it.
  `monitor/SPEC.md` describes every file the app reads.

Expect to adapt the paths and the status-file format to your own setup.

## Files

| file | what it is |
|---|---|
| `monitor/agents_app.py` | the app window (PyObjC) |
| `monitor/monitor_data.py` | the data engine; run it on its own to print the table and waiting list for an agent |
| `monitor/monitor_actions.py` | renames, replies, the already-resolved check and grouping |
| `monitor/alarm.py` | lets an agent call every other agent for help |
| `monitor/richtext.py` | renders bold, italics, highlights and emoji in descriptions |
| `monitor/build_app.py` | builds `/Applications/Agents.app`, a small launcher around `agents_app.py` |
| `monitor/app_live_test.py` | the live test of the running app |
| `monitor/SPEC.md` | the spec, traced line by line to the original requests |

## Run it

```
python3 monitor/build_app.py     # builds /Applications/Agents.app
open /Applications/Agents.app
```

`build_app.py` points at Homebrew's Python (`/opt/homebrew/bin/python3`); change `PYTHON` near its top if yours
lives elsewhere.
