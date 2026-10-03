"""Monthly prospective forecasts: lock before the month exists, score after it is published (ROADMAP 8e).

When the operator publishes trip month L, `lock` forecasts every station-day of month L+2 with the current
champion AND the baseline, from data published by then only, and writes

    forecasts/<system>/<yyyymm>/champion.csv, baseline.csv    station, date, forecast
    forecasts/<system>/<yyyymm>/challenger-<name>.csv         the same, for each challenger
    forecasts/<system>/<yyyymm>/lock.json                     configs, digests, as_of, created_at, file hashes

Challengers are the lab's backtest leads that have not been promoted: tests against the current champion whose
backtest CI lies above zero but that the kernel did not support at the backtest SESOI. Each is locked with its exact
config (seat-written code included) and scored against the baseline, at alpha / (number of challengers in the lock).
A challenger never changes the champion; its record is evidence for the lab and the owner.

The champion defaults to the knowledge graph's own record (`champion_config_from_knowledge`): the last promotion, or
the judge's BASELINE if there has never been one. `--run`/`--champion` are explicit manual overrides for one-off use.

`tick()` is the automatic path: called once an hour by ops/labd.py, it locks month L+2 as soon as its window opens,
flags a window that closed with nothing locked, and scores every locked month whose target has since published.
Locks and scores live in a dedicated git worktree of this repo, branch "prospective", at <repo_root>/../
nightshift-prospective -- never the main checkout's working tree. A lock or score is committed there and pushed to
origin, but only when the active `gh` account is this repo's owner (never switched automatically); otherwise the
commit stays local and the owner is alerted to push it by hand. The git commit and the GitHub push time are the
public timestamp; optionally stamp `lock.json` with OpenTimestamps too.

When month L+2 is published, `score` checks the lock (file hashes; created before the month began), scores both
forecasts on the station-days the censoring mask keeps, and writes scores/<system>/<yyyymm>.json. A judge change
between lock and score is surfaced (`judge_changed`), not refused: a prospective month cannot be re-run.

    python -m ops.prospective lock  --system chi [--run runs/latest | --champion yoy_level,holidays] [--no-challengers]
    python -m ops.prospective score --system chi --month 202611
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess

import numpy as np
import pandas as pd

from agents.common import describe_config, judge_digest
from judges import bikeshare as bj
from science import kernel as sk
from state.knowledge import Knowledge, config_id

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LockError(Exception):
    """A lock or a score that would not be a prospective test."""


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def champion_config_from_knowledge(knowledge_path, rig):
    """The lab's actual current champion: the knowledge graph's latest promotion (full config, so a seat-written
    `code:` champion works too), or the judge's BASELINE if nothing has ever been promoted. This is the default
    champion source for `lock` -- the same one true champion harness/daemon.py and ops/nightshift.py already trust,
    unlike a single run's own ledger (see `champion_from_run`)."""
    champ = Knowledge(knowledge_path, rig).current_champion()
    return dict(champ[0]) if champ else dict(bj.BASELINE)


def champion_from_run(run_root):
    """Manual override: the champion that ONE run's own ledger ended with (the baseline plus every change it itself
    promoted, in order). Only correct when that run made every promotion itself -- `make_ctx` resets
    `champion_history` to `[]` on every run, so a resumed run's ledger does not necessarily reflect the lab's actual
    current champion. Only understands judge-MENU keys: a seat-written `code:` champion cannot be expressed this
    way. Prefer the knowledge-graph default (`champion_config_from_knowledge`); keep this only to reproduce one
    specific run's own result."""
    with open(os.path.join(run_root, "ledger.json")) as f:
        return [h["promoted"] for h in json.load(f)["champion_history"]]


def config_for(keys):
    unknown = [k for k in keys if k not in bj.MENU]
    if unknown:
        raise LockError(f"not on the judge's menu: {unknown}")
    g = dict(bj.BASELINE)
    for k in keys:
        g.update(bj.MENU[k][1])
    return g


MAX_CHALLENGERS = 4
ALPHA = 0.05


def challengers(knowledge_path, rig, runs_dir, champion, limit=MAX_CHALLENGERS):
    """The backtest leads against `champion`: decided tests with the CI's lower bound above zero, best point first,
    one per treatment. Each config is read back from its run's locked prereg and must match the graph's record."""
    kg = Knowledge(knowledge_path, rig)
    best = {}
    for t in kg.tests(comparator=champion):
        d = t.get("decision") or {}
        if d.get("lo") is None or d["lo"] <= 0 or d.get("decision") == "supported":
            continue
        if t["treatment"] in best and best[t["treatment"]]["decision"]["point"] >= d["point"]:
            continue
        best[t["treatment"]] = t
    out = []
    for t in sorted(best.values(), key=lambda t: -t["decision"]["point"]):
        run = t["run"].removesuffix(" (imported)")
        path = os.path.join(runs_dir, run, "slices", t["slice"], "proof", "prereg_locked.json")
        try:
            with open(path) as f:
                config = json.load(f)["body"]["treatment"]
        except (OSError, ValueError, KeyError):
            continue  # the run's records are gone: nothing locked to take forward
        if config_id(config) != t["treatment"]:
            continue
        d = t["decision"]
        out.append(
            dict(
                name=t["change"].removeprefix("code:").replace(":", "_"),
                config=config,
                test=t["id"],
                backtest=dict(point=d["point"], lo=d["lo"], hi=d["hi"], decision=d["decision"]),
            )
        )
        if len(out) == limit:
            break
    return out


def month_start_utc(month):
    """The earliest moment the month begins anywhere in the US (UTC midnight is earlier than any US midnight)."""
    return dt.datetime(int(month[:4]), int(month[4:]), 1, tzinfo=dt.UTC)


def _parse_ts(iso):
    """A manifest/lock timestamp (may end in Z) as an aware datetime."""
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------- the prospective worktree (git/gh)
def prospective_worktree_path(repo_root):
    """Where lock/score write: a dedicated git worktree of this repo on branch "prospective", beside the main
    checkout -- never the main checkout's own working tree or branch."""
    return os.path.normpath(os.path.join(os.path.abspath(repo_root), os.pardir, "nightshift-prospective"))


def _run_git(run, args, cwd):
    run = run or subprocess.run
    return run(["git", *args], cwd=cwd, capture_output=True, text=True)


def ensure_prospective_worktree(repo_root, run=None):
    """Create the prospective worktree on first use (idempotent: a no-op once it exists). From origin/prospective
    if the remote already has that branch, else a new branch from the current HEAD. `run` is injectable (defaults
    to `subprocess.run`) so tests can point "origin" at a temp bare repo."""
    path = prospective_worktree_path(repo_root)
    if os.path.isdir(path):
        return path
    remote = _run_git(run, ["ls-remote", "--heads", "origin", "prospective"], repo_root)
    if (remote.stdout or "").strip():
        _run_git(run, ["fetch", "origin", "prospective"], repo_root)
        made = _run_git(run, ["worktree", "add", "-B", "prospective", path, "origin/prospective"], repo_root)
    else:
        made = _run_git(run, ["worktree", "add", "-b", "prospective", path], repo_root)
    if made.returncode != 0:
        raise LockError(f"git worktree add failed: {made.stderr or made.stdout}")
    return path


def repo_owner(repo_root, run=None):
    """The GitHub login this repo's `origin` remote belongs to, parsed from its URL (SSH or HTTPS)."""
    proc = _run_git(run, ["remote", "get-url", "origin"], repo_root)
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", (proc.stdout or "").strip())
    return m.group(1) if m else None


def gh_login(run=None):
    """The GitHub login `gh` is currently authenticated as, or None if `gh` fails or is not logged in."""
    run = run or subprocess.run
    try:
        proc = run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def commit_and_push(worktree, repo_root, rel_paths, message, run=None):
    """Commit `rel_paths` (relative to `worktree`) and push branch "prospective" to origin -- but only when the
    active `gh` account IS this repo's owner; never switch accounts to make it match. Returns `(pushed, reason)`;
    `reason` is set only when not pushed. The commit itself always lands locally first."""
    _run_git(run, ["add", *rel_paths], worktree)
    committed = _run_git(run, ["commit", "-m", message], worktree)
    if committed.returncode != 0 and "nothing to commit" not in (committed.stdout + committed.stderr):
        raise LockError(f"git commit failed: {committed.stderr or committed.stdout}")
    login, owner = gh_login(run), repo_owner(repo_root, run)
    if not login or not owner or login != owner:
        return False, f"gh is logged in as {login!r}, not the repo owner {owner!r}"
    pushed = _run_git(run, ["push", "origin", "prospective"], worktree)
    if pushed.returncode != 0:
        return False, f"git push failed: {pushed.stderr or pushed.stdout}"
    return True, None


# ---------------------------------------------------------------------------- lock / score
def lock(system, out_root, champion, now=None, challengers=()):
    """Forecast month L+2 from everything published so far, for `champion` (a full config dict -- see
    `champion_config_from_knowledge`) and the baseline. Refuses if that month has already begun."""
    now = now or dt.datetime.now(dt.UTC)
    panel = bj.load_panel()
    latest = max(panel["published"])
    month = bj.month_add(latest, 2)
    if now >= month_start_utc(month):
        raise LockError(f"{month} has already begun ({now.isoformat()}); a lock must precede its month")
    out = os.path.join(out_root, system, month)
    if os.path.exists(os.path.join(out, "lock.json")):
        raise LockError(f"{out} is already locked; a lock is never replaced")
    os.makedirs(out, exist_ok=True)
    arms = dict(champion=dict(champion), baseline=dict(bj.BASELINE))
    for c in challengers:
        arms[f"challenger-{c['name']}"] = c["config"]
    files = {}
    for arm, g in arms.items():
        uni, dates, pred = bj.predict_month(panel, panel["Y"], month, g)
        rows = [(panel["stations"][s], d.isoformat(), round(float(p), 4)) for s, ps in zip(uni, pred, strict=True)
                for d, p in zip(dates, ps, strict=True)]  # fmt: skip
        path = os.path.join(out, f"{arm}.csv")
        pd.DataFrame(rows, columns=["station", "date", "forecast"]).to_csv(path, index=False)
        files[f"{arm}.csv"] = sha256(path)
    record = dict(
        system=system,
        target_month=month,
        data_through=latest,
        as_of=panel["published"][latest],
        created_at=now.isoformat(),
        champion=dict(config=arms["champion"]),
        baseline=dict(config=arms["baseline"]),
        challengers={c["name"]: dict(config=c["config"], test=c["test"], backtest=c["backtest"]) for c in challengers},
        alpha_challengers=ALPHA / max(1, len(challengers)),
        judge_digest=judge_digest(bj),
        code_commit=_git_head(),
        files=files,
    )
    with open(os.path.join(out, "lock.json"), "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
    return record


def station_errors(system, month, out_root):
    """Check a lock and return (lock record, per-station abs errors of every arm (e_<arm>) and actuals, censor rate,
    masked, station-days kept, judge_changed) over the station-days the censoring mask keeps. `judge_changed` is
    True when the judge's current digest no longer matches the one stamped at lock time."""
    out = os.path.join(out_root, system, month)
    with open(os.path.join(out, "lock.json")) as f:
        record = json.load(f)
    for name, digest in record["files"].items():
        if sha256(os.path.join(out, name)) != digest:
            raise LockError(f"{name} does not match its locked hash: the forecast changed after lock")
    if dt.datetime.fromisoformat(record["created_at"]) >= month_start_utc(month):
        raise LockError(f"lock created {record['created_at']}, after {month} began: not a prospective test")
    panel = bj.load_panel()
    if month not in panel["published"]:
        raise LockError(f"{month} is not published yet")
    judge_changed = record.get("judge_digest") != judge_digest(bj)
    days = {d.isoformat(): i for i, d in enumerate(panel["days"]) if d.strftime("%Y%m") == month}
    s_idx = {s: i for i, s in enumerate(panel["stations"])}
    use_mask = bj.masked(panel, month)
    arms = [name.removesuffix(".csv") for name in sorted(record["files"])]
    fc = None
    for arm in arms:
        f = pd.read_csv(os.path.join(out, f"{arm}.csv")).rename(columns={"forecast": f"f_{arm}"})
        fc = f if fc is None else fc.merge(f, on=["station", "date"])
    si = fc["station"].map(s_idx)  # a station with no pickups in any published month has none in this one
    di = fc["date"].map(days).to_numpy()
    y = np.where(si.notna(), panel["Y"][si.fillna(0).astype(int).to_numpy(), di], 0.0)
    keep = np.ones(len(fc), bool)
    if use_mask:
        keep = np.where(si.notna(), panel["C"][si.fillna(0).astype(int).to_numpy(), di] == bj.OK, False)
    fc = fc.assign(y=y, keep=keep)
    kept = fc[fc["keep"]]
    by_station = kept.assign(**{f"e_{arm}": (kept[f"f_{arm}"] - kept["y"]).abs() for arm in arms})
    g = by_station.groupby("station")[[f"e_{arm}" for arm in arms] + ["y"]].sum()
    return record, g, float(1 - keep.mean()), bool(use_mask), int(len(kept)), judge_changed


def score(system, month, out_root, scores_root, sesoi=0.02, n_boot=2000):
    """Score a locked month once the operator has published it, then re-pool every scored month. A judge change
    since lock does not block scoring (a prospective month cannot be re-run); it is surfaced as `judge_changed`."""
    record, g, censor_rate, use_mask, n_kept, judge_changed = station_errors(system, month, out_root)
    est = sk.paired_effect(
        g[["e_champion"]].to_numpy(), g[["e_baseline"]].to_numpy(), ALPHA, n_boot, np.random.default_rng(0)
    )
    alpha_c = record.get("alpha_challengers", ALPHA)
    challenger = {}
    for name in record.get("challengers", {}):
        e = sk.paired_effect(
            g[[f"e_challenger-{name}"]].to_numpy(), g[["e_baseline"]].to_numpy(), alpha_c, n_boot,
            np.random.default_rng(0),
        )  # fmt: skip
        wape = float(g[f"e_challenger-{name}"].sum() / g["y"].sum())
        challenger[name] = dict(wape=wape, relative_wape_reduction=e, decision=sk.decide(e, sesoi), alpha=alpha_c)
    result = dict(
        system=system,
        target_month=month,
        lock=record,
        masked=use_mask,
        censor_rate=censor_rate,
        station_days=n_kept,
        stations=int(len(g)),
        judge_changed=judge_changed,
        wape_champion=float(g["e_champion"].sum() / g["y"].sum()),
        wape_baseline=float(g["e_baseline"].sum() / g["y"].sum()),
        relative_wape_reduction=est,
        challengers=challenger,
        scored_at=dt.datetime.now(dt.UTC).isoformat(),
    )
    os.makedirs(os.path.join(scores_root, system), exist_ok=True)
    with open(os.path.join(scores_root, system, f"{month}.json"), "w") as f:
        json.dump(result, f, indent=1, sort_keys=True)
    result["cumulative"] = cumulative(system, out_root, scores_root, sesoi, n_boot)
    return result


def cumulative(system, out_root, scores_root, sesoi, n_boot=2000):
    """The public claim: every published, locked month pooled (two-way bootstrap over stations x months), decided
    by the kernel at the prospective SESOI. A month is included whatever its result; none can be left out."""
    published = bj.load_panel()["published"]
    months = sorted(m for m in os.listdir(os.path.join(out_root, system)) if m in published)
    scored = {m: station_errors(system, m, out_root) for m in months}
    per = {m: r[1] for m, r in scored.items()}

    def pooled(arm, ms, alpha):
        stations = sorted(set().union(*(set(per[m].index) for m in ms)))
        err_t = np.column_stack([per[m][f"e_{arm}"].reindex(stations, fill_value=0).to_numpy() for m in ms])
        err_b = np.column_stack([per[m]["e_baseline"].reindex(stations, fill_value=0).to_numpy() for m in ms])
        est = sk.paired_effect(err_t, err_b, alpha, n_boot, np.random.default_rng(0))
        return dict(months=ms, alpha=alpha, estimate=est, decision=sk.decide(est, sesoi))

    out = dict(system=system, sesoi=sesoi, **pooled("champion", months, ALPHA))
    # a challenger pools every month it was locked in, at the strictest alpha any of those locks set
    names = sorted({n for r in scored.values() for n in r[0].get("challengers", {})})
    out["challengers"] = {}
    for n in names:
        ms = [m for m in months if n in scored[m][0].get("challengers", {})]
        alpha = min(scored[m][0].get("alpha_challengers", ALPHA) for m in ms)
        out["challengers"][n] = pooled(f"challenger-{n}", ms, alpha)
    with open(os.path.join(scores_root, system, "cumulative.json"), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    return out


# ---------------------------------------------------------------------------- automatic supervisor entry point
def tick(system, repo_root, knowledge_path, rig, alert, log, now=None):
    """One supervisor cycle (ops/labd.py calls this once an hour, inside its own try/except): lock month L+2 once
    its window opens, flag a window that closed with nothing locked, and score every locked month whose target has
    since published. `alert(kind, message, key=None)` records an owner alert (deduped by key); `log(str)` logs.
    Idempotent and cheap once there is nothing new to do; never raises -- a failure is an alert, not a crash."""
    now = now or dt.datetime.now(dt.UTC)
    out = dict(locked=None, scored=[], missed=[])
    try:
        worktree = ensure_prospective_worktree(repo_root)
    except LockError as e:
        alert("not pushed", f"prospective worktree unavailable: {e}", key=f"worktree:{system}")
        return out
    forecasts_root, scores_root = os.path.join(worktree, "forecasts"), os.path.join(worktree, "scores")
    try:
        with open(os.path.join(repo_root, "rigs", f"{rig}.json")) as f:
            sesoi = json.load(f)["decision_standards"]["prospective"]["sesoi"]
    except (OSError, KeyError, ValueError) as e:
        log(f"prospective: cannot read rigs/{rig}.json: {e}")
        return out
    try:
        manifest_published = bj.load_panel()["published"]
    except (OSError, ValueError) as e:
        log(f"prospective: no published data yet: {e}")
        return out
    if not manifest_published:
        return out

    target = bj.month_add(max(manifest_published), 2)
    sys_dir = os.path.join(forecasts_root, system)
    locked = {
        m
        for m in (os.listdir(sys_dir) if os.path.isdir(sys_dir) else [])
        if os.path.exists(os.path.join(sys_dir, m, "lock.json"))
    }

    if target not in locked and now < month_start_utc(target):
        try:
            champion = champion_config_from_knowledge(knowledge_path, rig)
            leads = (
                challengers(knowledge_path, rig, os.path.join(repo_root, "runs"), champion)
                if os.path.exists(knowledge_path)
                else []
            )
            lock(system, forecasts_root, champion, now=now, challengers=leads)
            pushed, reason = commit_and_push(
                worktree,
                repo_root,
                [os.path.join("forecasts", system, target)],
                f"Lock {system} {target} prospective forecasts",
            )
            if not pushed:
                alert("not pushed", f"lock {system} {target}: {reason}", key=f"not-pushed:lock:{system}:{target}")
            alert("locked", f"{system} {target}: champion {describe_config(bj, champion)}, {len(leads)} challenger(s)")
            log(f"prospective: locked {system} {target}")
            out["locked"] = target
            locked.add(target)
        except LockError as e:
            alert("not pushed", f"lock {system} {target} failed: {e}", key=f"lock-failed:{system}:{target}")

    for published_month, published_at in manifest_published.items():
        m = bj.month_add(published_month, 2)
        if m in locked or now < month_start_utc(m):
            continue
        if _parse_ts(published_at) < month_start_utc(m):
            alert("missed lock", f"{system} {m}: window closed with no lock on file", key=f"missed-lock:{system}:{m}")
            out["missed"].append(m)

    for m in sorted(locked):
        if m not in manifest_published or os.path.exists(os.path.join(scores_root, system, f"{m}.json")):
            continue
        try:
            r = score(system, m, forecasts_root, scores_root, sesoi=sesoi)
        except LockError as e:
            alert("not pushed", f"score {system} {m} failed: {e}", key=f"score-failed:{system}:{m}")
            continue
        pushed, reason = commit_and_push(
            worktree,
            repo_root,
            [os.path.join("scores", system, f"{m}.json"), os.path.join("scores", system, "cumulative.json")],
            f"Score {system} {m}",
        )
        if not pushed:
            alert("not pushed", f"score {system} {m}: {reason}", key=f"not-pushed:score:{system}:{m}")
        msg = (f"{system} {m}: champion WAPE {r['wape_champion']:.3f} vs baseline {r['wape_baseline']:.3f}, "
               f"cumulative {r['cumulative']['decision']}")  # fmt: skip
        if r["judge_changed"]:
            msg += " (judge changed since lock)"
        alert("scored", msg)
        log(f"prospective: scored {system} {m}")
        out["scored"].append(m)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ops.prospective", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["lock", "score"])
    ap.add_argument("--system", default="chi")
    ap.add_argument("--data", default=None, help="default: data/bikeshare/<system>")
    ap.add_argument("--run", default=None,
                     help="override: the champion that run's OWN ledger.json promoted (menu-key changes only; "
                          "a resumed run's ledger is NOT necessarily the lab's actual current champion -- see "
                          "--champion and the knowledge-graph default this falls back to)")  # fmt: skip
    ap.add_argument("--champion", default="",
                     help="override: comma-separated judge-menu keys for a manual champion config (overrides "
                          "--run; default: the knowledge graph's current champion, or BASELINE if never "
                          "promoted)")  # fmt: skip
    ap.add_argument("--month", default=None)
    ap.add_argument("--forecasts", default="forecasts")
    ap.add_argument("--scores", default="scores")
    ap.add_argument("--rigspec", default=os.path.join(REPO_ROOT, "rigs", "bikeshare-lab.json"))
    ap.add_argument("--knowledge", default=None, help="challengers from this graph; default: knowledge/<rig>.db")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--no-challengers", action="store_true")
    a = ap.parse_args(argv)
    bj.configure(dict(root=a.data or os.path.join("data", "bikeshare", a.system)))
    with open(a.rigspec) as f:
        spec = json.load(f)
    rig = spec.get("rig", "rig")
    kg = a.knowledge or os.path.join("knowledge", f"{rig}.db")
    if a.cmd == "lock":
        if a.champion:
            champion = config_for([k for k in a.champion.split(",") if k])
        elif a.run:
            champion = config_for(champion_from_run(a.run))
        else:
            champion = champion_config_from_knowledge(kg, rig)
        leads = []
        if not a.no_challengers and os.path.exists(kg):
            leads = challengers(kg, rig, a.runs_dir, champion)
        rec = lock(a.system, a.forecasts, champion, challengers=leads)
        path = os.path.join(a.forecasts, a.system, rec["target_month"])
        print(f"locked {path} (champion: {describe_config(bj, champion)}; "
              f"challengers: {[c['name'] for c in leads] or 'none'})")  # fmt: skip
        print("Publish the timestamp now:")
        print(f"  git add {path} && git commit -m 'Lock {a.system} forecasts for {rec['target_month']}' && git push")
    else:
        sesoi = spec["decision_standards"]["prospective"]["sesoi"]
        r = score(a.system, a.month, a.forecasts, a.scores, sesoi=sesoi)
        e = r["relative_wape_reduction"]
        wapes = f"champion WAPE {r['wape_champion']:.3f} vs baseline {r['wape_baseline']:.3f}"
        ci = f"reduction {e['point']:+.1%} [{e['lo']:+.1%}, {e['hi']:+.1%}]"
        print(f"{a.month}: {wapes}; {ci}; censor rate {r['censor_rate']:.0%}")
        if r["judge_changed"]:
            print("WARNING: the judge changed between lock and score; scored anyway (see judge_changed)")
        c = r["cumulative"]
        n, point = len(c["months"]), c["estimate"]["point"]
        print(f"all {n} scored months: {c['decision']} at SESOI {c['sesoi']:.0%} ({point:+.1%})")
        for name, ch in r["challengers"].items():
            e = ch["relative_wape_reduction"]
            ci = f"{e['point']:+.1%} [{e['lo']:+.1%}, {e['hi']:+.1%}]"
            print(f"  challenger {name}: {ci} vs baseline, {ch['decision']}")


if __name__ == "__main__":
    main()
