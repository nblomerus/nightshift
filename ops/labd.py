"""The lab, run continuously: keep testing ideas until the goal is reached, and ping the owner when it needs them.

Each cycle:
  1. refresh the data (new trip months, the censoring table from collected snapshots, a monthly street-events
     snapshot; failures are logged, not fatal);
  2. run one lab run (several campaigns) with the knowledge graph, so it continues from everything learned;
  3. check, with the kernel, whether the champion now beats the original baseline by the rigspec's goal;
  4. ping the owner, once per event, when: the goal is reached (and stop), the PI asks the owner for something the lab
     cannot get itself, the lab stalls (runs in a row that test nothing), or a run crashes (once a day per error);
  5. wait for the next slot by the wall clock, so a Mac that slept starts the next run as soon as it wakes.

Pings: a macOS notification and a line in knowledge/alerts.jsonl (also printed). The owner answers the PI with
`make reply MSG="..."`; the reply is in the PI's brief from its next plan. The supervisor never decides
anything: decisions come from the kernel inside each run; the goal check is the same paired effect the kernel uses.

    python -m ops.labd --rigspec rigs/bikeshare-lab.json --every 3600
    python -m ops.labd --print-launchd      # a plist that keeps it running
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import traceback

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTIFY = os.environ.get("NIGHTSHIFT_NOTIFY", "1") != "0"  # desktop notifications (tests turn them off)


def alert(path, kind, message, key=None, seen=None, notify=True):
    """Record and announce an event; with `key`, only the first time it is seen."""
    if key is not None and seen is not None:
        if key in seen:
            return False
        seen.add(key)
    rec = dict(t=dt.datetime.now(dt.UTC).isoformat(), kind=kind, message=message)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"ALERT {kind}: {message}", flush=True)
    if notify and NOTIFY and sys.platform == "darwin":
        text = message.replace('"', "'")[:230]
        subprocess.run(["osascript", "-e", f'display notification "{text}" with title "Nightshift: {kind}"'], check=False)
    return True


def goal_status(judge, champion, goal):
    """The champion vs the judge's original baseline on the design-B confirmation months, by the kernel's paired
    two-way bootstrap. Met when the CI's lower bound is at or above the goal."""
    from science import kernel as sk

    if "B" not in judge.DESIGNS:
        return None
    cache = {}
    t, c = (
        judge.evaluate(champion, "B", judge.data_keys("primary")[0], cache),
        judge.evaluate(judge.BASELINE, "B", judge.data_keys("primary")[0], cache),
    )
    est = sk.paired_effect(np.asarray(t["abs_err"]), np.asarray(c["abs_err"]), 0.05, 1000, np.random.default_rng(0))
    return dict(**est, goal=goal, met=bool(est["lo"] >= goal))


def refresh_data(judge_config, system, log):
    """New trip months and the censoring table, when the judge reads ingested data."""
    root = judge_config.get("root")
    if not root:
        return
    try:
        from ops.bikeshare_ingest import ingest

        with open(os.path.join(root, "manifest.json")) as f:
            before = set(json.load(f)["months"])
        after = set(ingest(system, root, log=log)["months"])
        if after - before:
            log(f"new trip months: {sorted(after - before)}")
    except Exception as e:  # network or operator hiccup: the lab still runs on what it has
        log(f"ingest skipped: {type(e).__name__}: {e}")
    try:
        from zoneinfo import ZoneInfo

        from ops.gbfs_collect import SYSTEMS
        from ops.gbfs_reduce import reduce_all

        gbfs = os.path.join(os.path.dirname(os.path.dirname(root)), "gbfs", system)
        if os.path.isdir(gbfs):
            today = dt.datetime.now(ZoneInfo(SYSTEMS[system]["tz"])).date().isoformat()
            reduce_all(gbfs, os.path.join(root, "censor_day.csv.gz"), today=today)
    except Exception as e:
        log(f"censor table skipped: {type(e).__name__}: {e}")
    try:  # street-event permits: a dated snapshot a month (docs/specs/bikeshare-events.md)
        from ops import events_ingest

        events = os.path.join(os.path.dirname(os.path.dirname(root)), "events", system)
        if system in events_ingest.SYSTEMS and events_ingest.due(events):
            events_ingest.ingest(system, events, log=log)
    except Exception as e:
        log(f"events snapshot skipped: {type(e).__name__}: {e}")


def cycle(llm, spec_path, knowledge, runs_dir, campaigns, state, alerts, max_idle=2, refresh=True, log=print):
    """One run of the lab and everything the supervisor checks after it. Returns 'goal' when the lab should stop."""
    from harness.daemon import load_rigspec, run

    spec = load_rigspec(spec_path)
    if refresh:
        refresh_data(spec.get("judge_config", {}), spec.get("judge_config", {}).get("system", "chi"), log)
    seen = set(state.setdefault("seen", []))
    name = "auto-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        _, ctx, _ = run(
            llm, root=os.path.join(runs_dir, name), n_campaigns=campaigns, rigspec=spec_path, knowledge=knowledge
        )
    except Exception as e:
        alert(
            alerts,
            "crashed",
            f"run {name} failed: {type(e).__name__}: {e}",
            key=f"crash:{dt.date.today()}:{type(e).__name__}:{e}",  # an outage that lasts days pings once a day
            seen=seen,
        )
        log(traceback.format_exc())
        state["seen"] = sorted(seen)
        return "crashed"
    try:
        return after_run(ctx, spec, name, knowledge, state, alerts, seen, max_idle, log)
    except Exception as e:  # a failure in the supervisor's own checks must not kill it silently
        alert(alerts, "crashed", f"checks after {name} failed: {type(e).__name__}: {e}",
              key=f"crash:{dt.date.today()}:after:{type(e).__name__}", seen=seen)  # fmt: skip
        log(traceback.format_exc())
        state["seen"] = sorted(seen)
        return "crashed"


def after_run(ctx, spec, name, knowledge, state, alerts, seen, max_idle, log):
    """What the supervisor checks after a run: idle streak, owner requests, stall, goal."""
    from agents.common import load_judge

    tested = sum(len(c["tested"]) + len(c["parked"]) + len(c.get("stalled", [])) for c in ctx["campaigns"])
    state["idle"] = 0 if tested else state.get("idle", 0) + 1
    state["runs"] = state.get("runs", 0) + 1
    log(f"{name}: {tested} slice(s) tested or stopped; idle streak {state['idle']}")
    # "Needs you": at most one ping a day, for open requests asked since the last ping. Read from the knowledge graph,
    # not from this run, so a request asked inside the cooldown is pinged once the cooldown ends, although the PI
    # (rightly) does not ask again while it is open.
    from state.knowledge import Knowledge

    pinged = state.setdefault("pinged_requests", {})  # request id -> the ask it was pinged for
    open_requests = Knowledge(knowledge, spec.get("rig", "rig")).requests("open")
    fresh = [r for r in open_requests if pinged.get(r["id"]) != r["asked"]]
    if fresh and time.time() - state.get("last_data_ping", 0) >= DATA_PING_EVERY:
        msg = "The PI asks: " + fresh[0]["what"] + (f" (+{len(fresh) - 1} more open)" if len(fresh) > 1 else "")
        alert(alerts, "needs you", msg + " | Open the mailbox on the lab floor (make ui) or run: make requests")
        state["last_data_ping"] = time.time()
        pinged.update({r["id"]: r["asked"] for r in fresh})
    if state["idle"] >= max_idle:
        msg = f"{state['idle']} runs in a row tested nothing (last: {name}). The lab needs new direction or data."
        msg += " The PI must now pick something; if it cannot, it files a request in the mailbox."
        # once per stall per day: the key changes with the day, so a stall that lasts is not reported only once
        alert(alerts, "stalled", msg, key=f"stall:{state['runs'] - state['idle']}:{dt.date.today()}", seen=seen)
    judge = load_judge(spec)
    goal = spec.get("decision_standards", {}).get("goal", {}).get("relative_wape_reduction")
    status = "running"
    if goal is not None:
        champion = ctx["champion"]
        g = goal_status(judge, champion, goal)
        state["goal"] = g
        if g and g["met"]:
            desc = ctx["champion_desc"]
            msg = f"The champion beats the baseline by {g['point']:+.1%} (CI low {g['lo']:+.1%}) >= goal {goal:.0%}: "
            alert(alerts, "goal reached", msg + desc[:120], key=f"goal:{desc}", seen=seen)
            status = "goal"
    state["seen"] = sorted(seen)
    state["last_run"] = name
    return status


DATA_PING_EVERY = 24 * 3600  # seconds between "needs you" pings while a request is open with the owner
DIGEST_HOUR = 21  # local time: one digest a day, after this hour


def maybe_digest(state, alerts, repo_root, rig, now=None):
    """Once a day (after DIGEST_HOUR), write knowledge/digest-<day>.md and ping it. A day whose digest was missed (the
    Mac slept through the evening) is sent the next morning."""
    from api.progress import build_progress, digest_text

    now = now or dt.datetime.now()
    last = state.get("digest_day")
    if now.hour >= DIGEST_HOUR:
        day = now.date().isoformat()
    elif last:
        day = (now.date() - dt.timedelta(days=1)).isoformat()
    else:
        return None
    if last is not None and last >= day:
        return None
    text = digest_text(build_progress(repo_root, rig), day)
    with open(os.path.join(repo_root, "knowledge", f"digest-{day}.md"), "w") as f:
        f.write(text + "\n")
    alert(alerts, "daily digest", text.replace("\n", " | "))
    state["digest_day"] = day
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ops.labd", description=__doc__.split("\n\n")[0])
    ap.add_argument("--rigspec", default=os.path.join(REPO_ROOT, "rigs", "bikeshare-lab.json"))
    ap.add_argument("--every", type=int, default=3600, help="seconds between the starts of runs")
    ap.add_argument("--campaigns", type=int, default=3)
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--knowledge", default=None, help="default: knowledge/<rig>.db")
    ap.add_argument("--max-idle", type=int, default=2, help="runs in a row that test nothing before a stall ping")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--print-launchd", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # launchd writes stdout to a file: keep knowledge/labd.log current
    if a.print_launchd:
        print(launchd_plist(a.every), end="")
        return 0
    from harness.daemon import load_rigspec
    from harness.llm import openai_compatible_llm

    spec = load_rigspec(a.rigspec)
    knowledge = a.knowledge or os.path.join("knowledge", f"{spec.get('rig', 'rig')}.db")
    alerts = os.path.join(os.path.dirname(knowledge), "alerts.jsonl")
    state_path = os.path.join(os.path.dirname(knowledge), "labd_state.json")
    state = load_state(state_path, alerts)
    if state.get("status") == "running":  # the last process died mid-run (killed, reloaded, power lost)
        print(f"resumed after an unclean exit during {state.get('last_run', 'a run')}", flush=True)
    watchdog(alerts)
    llm = openai_compatible_llm(
        os.environ["LLM_BASE_URL"],
        os.environ["REASONING_MODEL"],
        os.environ.get("UTILITY_MODEL", os.environ["REASONING_MODEL"]),
        os.environ.get("LLM_API_KEY", "none"),
    )
    llm = beating(llm)
    while True:
        t0 = time.time()
        beat()
        state.update(last_start=t0, every=a.every, status="running")
        save_state(state_path, state)
        try:
            status = cycle(llm, a.rigspec, knowledge, a.runs_dir, a.campaigns, state, alerts, a.max_idle)
            state["status"] = "waiting" if status != "goal" else "goal reached"
            maybe_digest(state, alerts, REPO_ROOT, spec.get("rig", "rig"))
        except Exception as e:  # last line of defence: report, then keep the schedule
            status = "crashed"
            state["status"] = "waiting"
            alert(alerts, "crashed", f"supervisor: {type(e).__name__}: {e}")
            traceback.print_exc()
        save_state(state_path, state)
        if status == "goal":
            print("goal reached: the lab stops", flush=True)
            return 0
        if a.once:
            return 0
        wait_until(max(t0 + a.every, time.time() + 60.0))


def wait_until(t, nap=60.0):
    """Sleep until wall-clock time `t`. macOS pauses `time.sleep` while the machine sleeps, so one long sleep would
    push the next run back by however long the lid was shut; short naps re-read the clock."""
    while (left := t - time.time()) > 0:
        beat()
        time.sleep(min(nap, left))


def save_state(path, state):
    """Write the supervisor's state atomically: a kill mid-write must not leave a truncated file."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, default=str)
    os.replace(tmp, path)


def load_state(path, alerts):
    """The saved state, or a fresh one if it is unreadable (the bad file is kept beside it, and reported)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        os.replace(path, path + ".corrupt")
        alert(alerts, "crashed", f"supervisor state unreadable ({type(e).__name__}); starting fresh, kept as .corrupt")
        return {}


# Watchdog: a live process that stops making progress (a wedged call, a deadlock) is not restarted by launchd, which
# only restarts a process that exits. Every LLM call and every nap beats; if no beat comes for WATCHDOG_S of *awake*
# time, the process reports and exits non-zero, and launchd starts it again. time.monotonic() does not advance while
# the Mac sleeps, so a closed lid never looks like a hang.
WATCHDOG_S = 2 * 3600
_BEAT = [time.monotonic()]


def beat():
    _BEAT[0] = time.monotonic()


def beating(llm):
    import functools

    @functools.wraps(llm)  # keeps the signature visible: the call recorder streams only if it sees on_progress
    def call(*a, **k):
        try:
            return llm(*a, **k)
        finally:
            beat()

    return call


def watchdog(alerts, limit=WATCHDOG_S, every=60.0, exit=os._exit):
    import threading

    def loop():
        while True:
            time.sleep(every)
            if time.monotonic() - _BEAT[0] > limit:
                alert(alerts, "hung", f"no progress for {limit / 3600:.1f} h of awake time; restarting the supervisor")
                exit(3)
                return  # one alert per hang: if exit() did not end the process (tests), the watchdog still stops

    threading.Thread(target=loop, daemon=True, name="labd-watchdog").start()


def launchd_plist(every):
    label = "com.nightshift.lab"
    cmd = f"cd {REPO_ROOT} && make labd EVERY={every}"
    log = os.path.join(REPO_ROOT, "knowledge", "labd.log")
    home = os.path.expanduser("~")
    # launchd starts with a bare PATH: pyenv (which the Makefile and a shell's startup files call) must be on it
    path = ":".join(
        [f"{home}/.pyenv/bin", f"{home}/.pyenv/shims", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-ic</string>
    <string>{cmd}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


if __name__ == "__main__":
    sys.exit(main())
