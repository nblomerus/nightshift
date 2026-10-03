"""The lab, run continuously: keep seeking improvement, and ping the owner when it needs them.

Each cycle:
  1. refresh the data (new trip months, the censoring table from collected snapshots, a monthly street-events
     snapshot; failures are logged, not fatal);
  2. run one lab run (several campaigns) with the knowledge graph, so it continues from everything learned;
  3. check, with the kernel, whether the champion now beats the original baseline by the rigspec's goal;
  4. ping the owner, once per event, when: the goal is reached (a milestone; the lab carries on unless the rigspec's goal
     says "stop"), the PI asks the owner for something the lab
     cannot get itself, the lab stalls (runs in a row that test nothing), or a run crashes (once a day per error);
  5. wait for the next slot by the wall clock, so a Mac that slept starts the next run as soon as it wakes; a run that
     the lid closing cut short (its connection died in the sleep) is not a crash: it starts again a minute after waking.

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
    try:  # a full disk must not turn the alert itself into the crash it reports
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        print(f"(could not record the alert: {e})", flush=True)
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


INGEST_ESCALATE = 3  # a month that fails to ingest this many cycles running is put to the owner
COLLECTOR_STALE_S = 3 * 3600  # GBFS snapshots arrive every 5 minutes; this long without one means the collector died


def refresh_data(judge_config, system, log, warn=None, state=None):
    """New trip months, the censoring table and the events snapshot, when the judge reads ingested data. Failures are
    logged, not fatal; `warn(kind, message, key)` puts the ones that persist to the owner (a month that keeps failing,
    unreadable snapshot days, a silent collector, ingest down for a day)."""
    warn = warn or (lambda *a, **k: None)
    state = state if state is not None else {}
    root = judge_config.get("root")
    if not root:
        return
    today = dt.date.today()
    try:
        from ops.bikeshare_ingest import ingest

        with open(os.path.join(root, "manifest.json")) as f:
            before = set(json.load(f)["months"])
        manifest = ingest(system, root, log=log)
        after = set(manifest["months"])
        if after - before:
            log(f"new trip months: {sorted(after - before)}")
        state["ingest_errors"] = 0
        for month, f in (manifest.get("failed") or {}).items():
            if f.get("attempts", 0) >= INGEST_ESCALATE:
                msg = f"trip month {month} has failed to ingest {f['attempts']} times since {f.get('first_seen')}"
                warn("data", f"{msg}: {f.get('error')}", f"ingest:{month}:{today}")
    except Exception as e:  # network or operator hiccup: the lab still runs on what it has
        state["ingest_errors"] = state.get("ingest_errors", 0) + 1
        log(f"ingest skipped: {type(e).__name__}: {e}")
        if state["ingest_errors"] >= 24:  # a day of hourly failures: new months (and the lock) would be missed
            warn("data", f"trip ingest has failed {state['ingest_errors']} cycles running: {type(e).__name__}: {e}",
                 f"ingest-down:{today}")  # fmt: skip
    try:
        from zoneinfo import ZoneInfo

        from ops.gbfs_collect import SYSTEMS
        from ops.gbfs_reduce import reduce_all

        gbfs = os.path.join(os.path.dirname(os.path.dirname(root)), "gbfs", system)
        if os.path.isdir(gbfs):
            local_today = dt.datetime.now(ZoneInfo(SYSTEMS[system]["tz"])).date().isoformat()
            _, skipped = reduce_all(gbfs, os.path.join(root, "censor_day.csv.gz"), today=local_today)
            if skipped:
                names = ", ".join(os.path.basename(p) for p, _ in skipped[:3])
                warn("data", f"{len(skipped)} GBFS snapshot day(s) unreadable, left out of the censoring mask: {names}",
                     f"gbfs-skipped:{today}")  # fmt: skip
            days = [os.path.join(gbfs, n) for n in os.listdir(gbfs) if n.endswith(".csv.gz")]
            newest = max((os.path.getmtime(p) for p in days), default=0)
            if days and time.time() - newest > COLLECTOR_STALE_S:
                hours = (time.time() - newest) / 3600
                msg = f"the GBFS collector for {system} has written nothing for {hours:.0f} h"
                warn("data", f"{msg}: the censoring mask stops growing", f"collector:{today}")
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
    seen = set(state.setdefault("seen", []))
    if refresh:

        def warn(kind, message, key):
            alert(alerts, kind, message, key=key, seen=seen)

        refresh_data(spec.get("judge_config", {}), spec.get("judge_config", {}).get("system", "chi"), log, warn, state)
    name = "auto-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    wall0, awake0 = time.time(), time.monotonic()
    try:
        _, ctx, _ = run(
            llm, root=os.path.join(runs_dir, name), n_campaigns=campaigns, rigspec=spec_path, knowledge=knowledge
        )
    except Exception as e:
        slept = (time.time() - wall0) - (time.monotonic() - awake0)  # monotonic time stops while the Mac sleeps
        if slept > SLEEP_GAP_S:  # the lid closed mid-run and the connection died with it: not a fault, start again
            log(f"run {name} interrupted by {slept / 60:.0f} min of sleep ({type(e).__name__}: {e}); restarting")
            state["seen"] = sorted(seen)
            return "interrupted"
        alert(
            alerts,
            "crashed",
            f"run {name} failed: {type(e).__name__}: {e}",
            # an outage that lasts days pings once a day; not keyed on the text, which holds this run's timestamped path
            key=f"crash:{dt.date.today()}:{type(e).__name__}",
            seen=seen,
        )
        log(traceback.format_exc())
        state["seen"] = sorted(seen)
        return "crashed"
    try:
        status = after_run(ctx, spec, name, knowledge, state, alerts, seen, max_idle, log)
        if refresh:  # the same switch as the data refresh: both reach outside (data, git); tests turn them off
            prospective_tick(spec, knowledge, alerts, seen, log)
        state["seen"] = sorted(seen)
        return status
    except Exception as e:  # a failure in the supervisor's own checks must not kill it silently
        alert(alerts, "crashed", f"checks after {name} failed: {type(e).__name__}: {e}",
              key=f"crash:{dt.date.today()}:after:{type(e).__name__}", seen=seen)  # fmt: skip
        log(traceback.format_exc())
        state["seen"] = sorted(seen)
        return "crashed"


def after_run(ctx, spec, name, knowledge, state, alerts, seen, max_idle, log):
    """What the supervisor checks after a run: idle streak, owner requests, stall, goal."""
    from agents.common import load_judge

    # Progress is a decision or a park; a slice stalled mid-workflow (a seat kept failing) is a fault, not progress.
    tested = sum(len(c["tested"]) + len(c["parked"]) for c in ctx["campaigns"])
    stuck = [s for c in ctx["campaigns"] for s in c.get("stalled", [])]
    if stuck:
        alert(alerts, "handler stuck", f"{len(stuck)} slice(s) stalled mid-workflow in {name} (a seat kept failing): "
              f"{', '.join(stuck[:3])}", key=f"stuck:{dt.date.today()}", seen=seen)  # fmt: skip
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
            # a milestone: the lab keeps seeking improvement unless the rigspec says the goal ends it
            if spec["decision_standards"]["goal"].get("stop"):
                status = "goal"
    state["seen"] = sorted(seen)
    state["last_run"] = name
    return status


SLEEP_GAP_S = 300  # a run that failed after the Mac slept this long during it was interrupted, not broken
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
    missing = [v for v in ("LLM_BASE_URL", "REASONING_MODEL") if not os.environ.get(v)]
    if missing:  # launchd restarts us every 5 minutes: say why, once a day, instead of crash-looping silently
        seen = set(state.setdefault("seen", []))
        alert(alerts, "crashed", f"supervisor cannot start: {', '.join(missing)} not set in its environment",
              key=f"env:{dt.date.today()}", seen=seen)  # fmt: skip
        state["seen"] = sorted(seen)
        try:
            save_state(state_path, state)
        except OSError as e:  # the dedup key could not be kept: say so in the log, without another notification
            print(f"could not save supervisor state ({e}); the alert above may repeat on each restart", flush=True)
        return 2
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
        try_save(state_path, state, alerts)  # a state file that cannot be written must not stop the lab's work
        try:
            status = cycle(llm, a.rigspec, knowledge, a.runs_dir, a.campaigns, state, alerts, a.max_idle)
            state["status"] = "waiting" if status != "goal" else "goal reached"
            maybe_digest(state, alerts, REPO_ROOT, spec.get("rig", "rig"))
        except Exception as e:  # last line of defence: report, then keep the schedule
            status = "crashed"
            state["status"] = "waiting"
            seen = set(state.setdefault("seen", []))
            key = f"supervisor:{dt.date.today()}:{type(e).__name__}"
            alert(alerts, "crashed", f"supervisor: {type(e).__name__}: {e}", key=key, seen=seen)
            state["seen"] = sorted(seen)
            traceback.print_exc()
        try_save(state_path, state, alerts)
        if status == "goal":
            print("goal reached: the lab stops", flush=True)
            return 0
        if a.once:
            return 0
        # a run cut short by sleep starts again a minute after waking; otherwise keep the hourly slot
        wait_until(time.time() + 60.0 if status == "interrupted" else max(t0 + a.every, time.time() + 60.0))


def wait_until(t, nap=60.0):
    """Sleep until wall-clock time `t`. macOS pauses `time.sleep` while the machine sleeps, so one long sleep would
    push the next run back by however long the lid was shut; short naps re-read the clock."""
    while (left := t - time.time()) > 0:
        beat()
        time.sleep(min(nap, left))


def prospective_tick(spec, knowledge, alerts, seen, log):
    """Lock and score the monthly prospective forecasts when due (ops/prospective.py). Only for the bike-share judge;
    a failure is reported, never fatal."""
    if spec.get("judge") != "judges.bikeshare":
        return
    try:
        from ops import prospective

        prospective.tick(spec.get("judge_config", {}).get("system", "chi"), REPO_ROOT, knowledge, spec.get("rig", "rig"),
                         alert=lambda kind, message, key=None: alert(alerts, kind, message, key=key, seen=seen),
                         log=log)  # fmt: skip
    except Exception as e:
        alert(alerts, "lock failed", f"prospective tick: {type(e).__name__}: {e}",
              key=f"prospective:{dt.date.today()}:{type(e).__name__}", seen=seen)  # fmt: skip
        log(traceback.format_exc())


def try_save(path, state, alerts):
    """save_state, reporting a failure (a full disk, a read-only volume) once a day instead of stopping the loop."""
    try:
        save_state(path, state)
    except OSError as e:
        seen = set(state.setdefault("seen", []))  # kept in memory: the file that would hold it cannot be written
        alert(alerts, "crashed", f"supervisor state not saved: {e}", key=f"state-save:{dt.date.today()}", seen=seen)
        state["seen"] = sorted(seen)


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
