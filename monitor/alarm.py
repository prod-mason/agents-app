#!/usr/bin/env python3
"""alarm.py: any agent can ring an alarm that asks ALL the other agents for help.

Mason, 10 Sep 2026: "an alarm that can be set by an agent if it thinks it needs the help of all the other agents.
And an individual agent can check on the status of the agents for just basic common sense communication if needed."

Common sense, not ceremony. An alarm is for something one lane cannot fix alone and that other lanes would want to
know about now: a shared resource about to break (disk, an install, his session), a finding that changes other lanes'
work, a mistake that may have spread. It is NOT for questions for Mason (those go on the stack) or for one other lane
(message that lane directly).

  python3 alarm.py raise --from "<your session name>" --why "<what is wrong and what help you need>"
      Writes the alarm to lab-common/ALARMS.jsonl and prints the message to send, plus every live session to send it
      to. Then YOU send it to each of them with SendMessage; a script cannot wake another session, you can.
  python3 alarm.py ack <id> --from "<your session name>" [--note "what you are doing about it"]
  python3 alarm.py resolve <id> --from "<your session name>" --note "how it was settled"
  python3 alarm.py list            open alarms (the Agents app and monitor_data.py show these first)
  python3 alarm.py list --all      every alarm ever, with its acks
  python3 alarm.py --json list     machine-readable
  python3 alarm.py --selftest      planted controls

The ledger is append-only: nothing is ever edited or deleted; an alarm's state is the last event about it.
"""
import argparse, glob, hashlib, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
LEDGER = os.path.join(LAB, "ALARMS.jsonl")
SESSIONS = os.path.expanduser("~/.claude/sessions")
MIN_WHY = 40          # a bell with no reason is noise; forty characters is one real sentence
STALE_HOURS = 24


def now_local():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def pretty(ts):
    try:
        t = time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        return time.strftime("%a %d %b %I:%M %p", t).replace(" 0", " ")
    except Exception:
        return ts


def read(ledger=None):
    out = []
    try:
        with open(ledger or LEDGER, errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


def append(rec, ledger=None):
    with open(ledger or LEDGER, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def state(events):
    """id -> {raised event, acks, resolved event or None}"""
    al = {}
    for e in events:
        i = e.get("id")
        if not i:
            continue
        if e.get("event") == "raised":
            al[i] = {"raised": e, "acks": [], "resolved": None}
        elif i in al and e.get("event") == "ack":
            al[i]["acks"].append(e)
        elif i in al and e.get("event") == "resolved":
            al[i]["resolved"] = e
    return al


def open_alarms(ledger=None):
    """What monitor_data.py and the Agents app show: raised and not resolved, oldest first."""
    rows = []
    for i, a in state(read(ledger)).items():
        if a["resolved"]:
            continue
        r = a["raised"]
        try:
            age_h = (time.time() - time.mktime(time.strptime(r["t"][:19], "%Y-%m-%dT%H:%M:%S"))) / 3600
        except Exception:
            age_h = 0
        rows.append({"id": i, "from": r.get("from", "?"), "why": r.get("why", ""), "t": r.get("t", ""),
                     "when": pretty(r.get("t", "")), "acks": [x.get("from", "?") for x in a["acks"]],
                     "stale": age_h > STALE_HOURS})
    return sorted(rows, key=lambda x: x["t"])


def live_sessions():
    names = []
    for f in glob.glob(os.path.join(SESSIONS, "*.json")):
        try:
            d = json.load(open(f))
            os.kill(int(d["pid"]), 0)
        except Exception:
            continue
        if d.get("name"):
            names.append(d["name"])
    return sorted(set(names), key=str.lower)


def new_id(frm, why):
    return "A" + time.strftime("%m%d-%H%M%S") + "-" + hashlib.sha1((frm + why).encode()).hexdigest()[:4]


def cmd_raise(frm, why, ledger=None, sessions=None):
    why = " ".join(why.split())
    if len(why) < MIN_WHY:
        raise SystemExit(f"REFUSED: say what is wrong and what help you need, in at least {MIN_WHY} characters. "
                         f"The other agents will stop their work to read it.")
    i = new_id(frm, why)
    append({"id": i, "event": "raised", "t": now_local(), "from": frm, "why": why}, ledger)
    others = [s for s in (sessions if sessions is not None else live_sessions()) if s.lower() != frm.lower()]
    msg = (f"ALARM {i} from {frm}: {why} "
           f"If you can help, reply to {frm} and run: python3 \"{os.path.join(HERE, 'alarm.py')}\" ack {i} --from \"<your name>\" --note \"<what you are doing>\". "
           f"If you cannot, carry on; the alarm stays on the Agents app until it is resolved.")
    return i, msg, others


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ring, answer and settle alarms across every agent.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("raise"); r.add_argument("--from", dest="frm", required=True); r.add_argument("--why", required=True)
    a = sub.add_parser("ack"); a.add_argument("id"); a.add_argument("--from", dest="frm", required=True); a.add_argument("--note", default="")
    z = sub.add_parser("resolve"); z.add_argument("id"); z.add_argument("--from", dest="frm", required=True); z.add_argument("--note", required=True)
    l = sub.add_parser("list"); l.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd == "raise":
        i, msg, others = cmd_raise(args.frm, args.why)
        if args.json:
            print(json.dumps({"id": i, "message": msg, "send_to": others}, indent=1)); return 0
        print(f"Raised {i}. It is on the Agents app now.\n")
        print("NOW SEND THIS, with SendMessage, to each session below (a script cannot wake them; you can):\n")
        print(msg + "\n")
        print("Send to: " + ", ".join(others))
        return 0
    if args.cmd in ("ack", "resolve"):
        st = state(read())
        if args.id not in st:
            raise SystemExit(f"No alarm {args.id}. Run: python3 alarm.py list --all")
        if args.cmd == "resolve" and st[args.id]["resolved"]:
            print(f"{args.id} was already resolved by {st[args.id]['resolved'].get('from')}."); return 0
        ev = "ack" if args.cmd == "ack" else "resolved"
        append({"id": args.id, "event": ev, "t": now_local(), "from": args.frm, "note": " ".join(args.note.split())})
        print(f"{'Acknowledged' if ev == 'ack' else 'Resolved'} {args.id}. Tell {st[args.id]['raised'].get('from')} directly too.")
        return 0
    if args.cmd == "list" or args.cmd is None:
        if getattr(args, "all", False):
            rows = []
            for i, a in state(read()).items():
                rows.append({"id": i, "from": a["raised"].get("from"), "why": a["raised"].get("why"), "when": pretty(a["raised"].get("t", "")),
                             "acks": [(x.get("from"), x.get("note")) for x in a["acks"]],
                             "resolved": (a["resolved"] or {}).get("note") if a["resolved"] else None})
        else:
            rows = open_alarms()
        if args.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False)); return 0
        if not rows:
            print("No open alarms." if not getattr(args, "all", False) else "No alarms have ever been raised."); return 0
        for x in rows:
            head = f"{x['id']}  {x['when']}  from {x['from']}"
            if x.get("stale"): head += "  (open more than a day)"
            if "resolved" in x and x["resolved"] is not None: head += "  RESOLVED"
            print(head); print("  " + x["why"])
            if x.get("acks"): print("  answered by: " + ", ".join(a if isinstance(a, str) else a[0] for a in x["acks"]))
        return 0
    ap.print_help(); return 0


def selftest():
    res = []
    d = tempfile.mkdtemp(); led = os.path.join(d, "A.jsonl")
    # 1. a bell with no reason is refused and writes nothing
    try:
        cmd_raise("Dreiling_Clip", "help", led, []); ok = False
    except SystemExit:
        ok = not os.path.exists(led)
    res.append(("an alarm without a real reason is refused and writes nothing", ok))
    # 2. raise, then it is open; the raiser is not on its own send list
    i, msg, others = cmd_raise("Dreiling_Clip", "The shared build tree is corrupt and every lane that builds tonight will ship a stale binary.", led, ["Dreiling_Clip", "Dreiling_EQ", "Storage"])
    res.append(("a raised alarm is open, and the raiser is not told to message itself",
                [x["id"] for x in open_alarms(led)] == [i] and others == ["Dreiling_EQ", "Storage"] and i in msg))
    # 3. an ack does not close it; a resolve does
    append({"id": i, "event": "ack", "t": now_local(), "from": "Dreiling_EQ", "note": "pausing my build"}, led)
    still = [x["acks"] for x in open_alarms(led)] == [["Dreiling_EQ"]]
    append({"id": i, "event": "resolved", "t": now_local(), "from": "Dreiling_Clip", "note": "tree rebuilt"}, led)
    res.append(("an answer keeps it open with who answered; a resolve closes it", still and open_alarms(led) == []))
    # 4. a corrupt line never hides a real alarm
    with open(led, "a") as f: f.write("{not json\n")
    j, _, _ = cmd_raise("Storage", "Free disk will reach the floor within the hour and two long runs are registered.", led, [])
    res.append(("a corrupt ledger line does not hide a real alarm", [x["id"] for x in open_alarms(led)] == [j]))
    print("PLANTED CONTROLS")
    for n, ok in res: print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
    bad = [n for n, ok in res if not ok]
    print(); print(f"{len(bad)} FAILED." if bad else f"All {len(res)} controls pass.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
