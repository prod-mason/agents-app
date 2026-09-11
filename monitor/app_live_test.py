#!/opt/homebrew/bin/python3
"""app_live_test.py - the Agents window's live test, in its own scratch cmux window.

    /opt/homebrew/bin/python3 app_live_test.py [out_dir] [--steps a,b,c]

What it does, in order:
  1. Makes a scratch cmux window ("Agents test app <pid>", not focused) running monitor_actions'
     fake Claude prompt (FIXTURE): it shows an idle prompt, a permission question, a half typed prompt
     or a menu, as told by a mode file, and records every byte typed into it.
  2. Seeds a TEST ledger (in the cache folder, never lab-common) with rows naming a few real waiting
     items, so the free check finds them answered, and a TEST alarm ledger with one open alarm.
  3. Runs agents_app.py as a separate process in TEST MODE (AGENTS_TEST_WORKSPACE = the scratch window,
     AGENTS_TEST_LEDGER, AGENTS_TEST_ALARMS, its own prefs file, grouping from cache only) with
     AGENTS_DRIVE: the app takes its own screenshots (screencapture -l, never raising the window) and
     answers through the same functions a click or a key would call.
  4. Reads what arrived in the scratch window and the test ledger, and the scratch window's name
     after the rename step; prints PASS or FAIL per check.
  5. Closes the scratch window (cmux close-workspace) and removes the seeded files.

Model calls: the "deliver" and "multi" steps each make ONE real checker call (Claude Haiku 4.5), for
the one item in each that the free checks cannot settle. Every other step uses no model.
Writes: out_dir (screenshots, drive.json, captured.txt, app-stderr.log), and in
~/Library/Caches/com.masondean.agents/ the seeded files and monitor_actions' test outbox and ledger
mirror, all removed at the end.
Never touches his workspaces: every send and rename in the app goes to the scratch window.
"""
import json, os, re, subprocess, sys, time, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CMUX = "/Applications/cmux.app/Contents/Resources/bin/cmux"
PY = "/opt/homebrew/bin/python3"
CACHE = os.path.expanduser("~/Library/Caches/com.masondean.agents")
DEFAULT_STEPS = ("window,hover,group,storage,alarm,card,mode:idle,deliver,multi,mode:permission,held,msgheld,"
                 "mode:idle,msg,together,rename,small")


def env_clean():
    return {k: v for k, v in os.environ.items() if not k.startswith("CMUX_") and not k.startswith("AGENTS_")}


def cmux(*args, timeout=15):
    r = subprocess.run([CMUX, *args], capture_output=True, text=True, timeout=timeout, env=env_clean())
    return r.returncode, r.stdout, r.stderr


def ws_name(ws):
    rc, out, _ = cmux("--id-format", "both", "list-workspaces")
    for line in out.split("\n"):
        if ws in line:
            return line
    return ""


def main(argv):
    out_dir = argv[0] if argv and not argv[0].startswith("--") else os.path.join(HERE, "screenshots")
    steps = DEFAULT_STEPS
    if "--steps" in argv:
        steps = argv[argv.index("--steps") + 1]
    os.makedirs(out_dir, exist_ok=True)
    import monitor_actions as act
    import monitor_data as md
    work = os.path.join(CACHE, f"apptest-{os.getpid()}")
    os.makedirs(work, exist_ok=True)
    mode, cap, scr, fix = (os.path.join(work, n) for n in ("mode", "capture", "screens.json", "fixture.py"))
    ledger, alarms, prefs = (os.path.join(work, n) for n in ("ANSWERS-test.md", "ALARMS-test.jsonl", "prefs.json"))
    json.dump(act.fake_screens(), open(scr, "w", encoding="utf-8"))
    open(fix, "w").write(act.FIXTURE)
    open(mode, "w").write("idle")
    open(cap, "wb").close()
    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))

    w = md.waiting()
    items = [i for i in w.get("items") or [] if i.get("id")]
    # the card item and two of the three multi items are seeded as answered; the other two go to the checker
    # Only items whose owning agent has an open window: since 11 Sep a reply for a lane with no window
    # is held for that lane rather than typed into the coordinator's, so it would never reach the
    # scratch window. Read only: the real windows are looked up, nothing is sent here.
    try:
        wins = act.windows()
    except Exception:
        wins = {}
    open_ids = []
    for i in items:
        if len(open_ids) >= 6:
            break
        if act._target(act.owner_lane(i), wins).get("workspace") is None:
            continue
        if not i.get("may_be_settled") and act.free_check(i)[0] is None:
            open_ids.append(i["id"])
    card_id, deliver_id = open_ids[0], open_ids[1]
    multi = open_ids[2:5]
    seeded = [card_id, multi[0], multi[1]]
    with open(ledger, "w") as f:
        f.write("| subject | when, how | his words / the ruling |\n|---|---|---|\n")
        for iid in seeded:
            f.write(f"| test seed for the Agents app live test | test, item {iid} | answered in this test ledger only |\n")
    with open(alarms, "w") as f:
        f.write(json.dumps({"id": "apptest01", "event": "raised", "from": "Agents app test",
                            "why": "A planted test alarm: the Agents window must show this banner in red and open its full text on a click.",
                            "t": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
    name = f"Agents test app {os.getpid()}"
    ws = None
    try:
        rc, out, err = cmux("new-workspace", "--name", name, "--focus", "false", "--command",
                            f"{PY} '{fix}' '{mode}' '{cap}' '{scr}'")
        time.sleep(1.0)
        rc2, lst, _ = cmux("--id-format", "both", "list-workspaces")
        for line in lst.split("\n"):
            if line.rstrip().endswith(name):
                m = re.search(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27}", line)
                ws = m.group(0) if m else None
        check("scratch window made", rc == 0 and ws, f"{out.strip()} {ws}")
        if not ws:
            return 1
        env = env_clean()
        env.update(AGENTS_TEST_WORKSPACE=ws, AGENTS_TEST_LEDGER=ledger, AGENTS_TEST_ALARMS=alarms,
                   AGENTS_PREFS=prefs, AGENTS_GROUPING="cache-only", AGENTS_DRIVE=out_dir, AGENTS_DRIVE_STEPS=steps,
                   AGENTS_DRIVE_ITEM=card_id, AGENTS_DRIVE_OPEN_ITEM=deliver_id, AGENTS_DRIVE_MULTI=",".join(multi),
                   AGENTS_DRIVE_MODEFILE=mode, AGENTS_DRIVE_RENAME="Agents test renamed by the app")
        t0 = time.time()
        with open(os.path.join(out_dir, "app-stderr.log"), "w") as errf:
            p = subprocess.Popen([PY, os.path.join(HERE, "agents_app.py"), "-ApplePersistenceIgnoreState", "YES"],
                                 env=env, stdout=subprocess.DEVNULL, stderr=errf, cwd=work)
            time.sleep(6)
            try:
                from AppKit import NSRunningApplication
                ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(p.pid)
                name = str(ra.localizedName()) if ra is not None else None
                icon = ra.icon() if ra is not None else None
                check("identity: macOS names the running app Agents (Dock and menu bar), not Python", name == "Agents",
                      f"localizedName {name!r}, bundle {ra.bundleIdentifier() if ra is not None else None}, icon {'set' if icon is not None else 'none'}")
            except Exception as ex:
                check("identity: macOS names the running app Agents", False, f"{type(ex).__name__}: {ex}")
            try:
                p.wait(timeout=400)
            except subprocess.TimeoutExpired:
                p.terminate()
                check("app finished its steps", False, "timed out after 400 s")
        check("app ran every step and quit by itself", p.returncode == 0, f"exit {p.returncode} after {time.time() - t0:.0f} s")
        got = open(cap, "rb").read().decode("utf-8", "replace")
        print("  what arrived in the scratch window:")
        for line in got.split("\r"):
            if line.strip():
                print("     |", line[:220])
        d = json.load(open(os.path.join(out_dir, "drive.json")))["steps"]
        check("card: the seeded item came back RESOLVED by the free checks",
              d.get("card", {}).get("phase") == "card" and "the free checks" in str(d.get("card", {}).get("card")),
              str((d.get("card", {}).get("card") or {}).get("rows")))
        ae = d.get("card", {}).get("after_E") or {}
        check("card: E puts his text back, cursor at the end", ae.get("editing") and ae.get("field", "").startswith("Test reply")
              and ae.get("cursor", (0,))[0] == len(ae.get("field", "")), str(ae))
        check("card: nothing from the card step was typed", "please go ahead as you proposed" not in got)
        if "deliver" in d:
          check("deliver: the open item's reply arrived once, with the SPEC prefix",
              got.count("no action needed.") >= 1 and got.count("(open path)") == 1 and "[From the Agents app, about: " in got,
              str(d.get("deliver", {}).get("status")))
        if "multi" in d:
            mc = d.get("multi", {}).get("dock_card") or {}
            check("multi: ONE card listing the two seeded items", len(mc.get("rows") or []) == 2, str([r[0] for r in mc.get("rows") or []]))
            check("multi: the open item went at once, alone", got.count("(several at once)") == 1, "")
        msgs = [v for k, v in d.items() if k == "msg"]
        check("message bar: typed into the scratch window once with the prefix",
              got.count("[From the Agents app] Agents app build test: message bar") == 1)
        check("together: the lead got one request to confer", got.count("[From the Agents app, work it out together]") == 1,
              str(d.get("together", {}).get("status")))
        led = open(ledger).read() if os.path.exists(ledger) else ""
        want_replies = ("deliver" in d) + ("multi" in d)
        check("ledger: his words landed in the TEST ledger", led.count("Reply from the Agents app") >= want_replies
              and ("Said from the Agents app" in led) == ("msg" in d or "msgheld" in d),
              f"{led.count('Reply from the Agents app')} reply rows, {led.count('Said from the Agents app')} message rows")
        real = [f for f in os.listdir(os.path.dirname(HERE)) if f.startswith("ANSWERS-")]
        real_hit = any("Agents app build test" in open(os.path.join(os.path.dirname(HERE), f), errors="ignore").read() for f in real)
        check("ledger: nothing of this test in the real ANSWERS ledgers", not real_hit)
        if "rename" in d:
            line = ws_name(ws)
            check("rename: the scratch window got the new name (test mode redirects it there)",
                  line.rstrip().endswith("Agents test renamed by the app"), f"{line.strip()} | footer: {d['rename'].get('footer')}")
        hd = d.get("held", {})
        if hd:
            sl = hd.get("status_line") or []
            check("held: an item reply to a window showing a permission question waits to deliver, with Cancel, "
                  "and nothing is typed; Cancel cancels it",
                  bool(sl) and str(sl[0]).startswith("Waiting to deliver to the") and sl[1] == "held"
                  and hd.get("cancel_shown") is True and "(held path)" not in got
                  and "Cancelled" in str((hd.get("after_cancel") or [""])[0]),
                  f"{sl[:2]} | after Cancel: {hd.get('after_cancel')}")
        mh = d.get("msgheld", {})
        if mh:
            check("message bar: a permission question holds it, nothing typed, Cancel keeps his words",
                  (mh.get("msg") or {}).get("phase") == "held" and (mh.get("after_cancel") or {}).get("phase") is None
                  and "message bar" in (mh.get("field_after_cancel") or ""), str((mh.get("after_cancel") or {}).get("status")))
        check("rename: Escape cancelled the second edit", d.get("rename", {}).get("escape_cancelled") is True)
        for k, v in d.items():
            if isinstance(v, dict) and v.get("error"):
                check(f"step {k} ran without an error", False, v["error"])
        with open(os.path.join(out_dir, "captured.txt"), "w") as f:
            f.write(got)
    finally:
        if ws:
            open(mode, "w").write("quit")
            time.sleep(0.5)
            rc, out, err = cmux("close-workspace", "--workspace", ws)
            check("scratch window closed", rc == 0, (out or err).strip())
        shutil.rmtree(work, ignore_errors=True)
        own = act.test_outbox_name(ws) if ws else "outbox-test-none.json"   # this run's own, never another test's
        for leftover in (own, own + ".lock", "ledger-mirror-test.jsonl"):
            try:
                os.remove(os.path.join(CACHE, leftover))     # monitor_actions' test-mode files, as its own live test does
            except OSError:
                pass
    print(f"{sum(results)} of {len(results)} checks pass")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
