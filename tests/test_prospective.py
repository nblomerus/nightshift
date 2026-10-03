"""ROADMAP 8e: monthly prospective lock and score (offline, synthetic trips)."""

import datetime as dt
import json
import os
import subprocess
import types

import pandas as pd
import pytest

from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from ops import prospective as pr
from state.knowledge import Knowledge
from tests.fixtures.bikeshare.synth import stub_get, trip_zips


def sk_decisions():
    return {"supported", "harmful", "no_effect", "inconclusive"}


BEFORE = dt.datetime(2025, 9, 15, tzinfo=dt.UTC)  # 202508 is published (early Sept); 202510 has not begun


@pytest.fixture
def system(tmp_path):
    """Trips published through 202508; the zips for 202509-202510 exist but are not ingested yet."""
    zips = trip_zips(last="202510")
    root = tmp_path / "data" / "chi"
    ing.ingest("chi", str(root), last="202508", get=stub_get(zips), log=lambda *_: None)
    bj.configure(dict(root=str(root)))
    return dict(root=root, zips=zips, forecasts=tmp_path / "forecasts", scores=tmp_path / "scores")


def publish_rest(s):
    ing.ingest("chi", str(s["root"]), get=stub_get(s["zips"]), log=lambda *_: None)
    bj.configure(dict(root=str(s["root"])))


def test_lock_then_score_reproduces_a_hand_computed_wape(system):
    rec = pr.lock("chi", str(system["forecasts"]), pr.config_for(["station_dow", "holidays"]), now=BEFORE)
    assert rec["target_month"] == "202510" and rec["data_through"] == "202508"
    assert rec["champion"]["config"]["station_dow"] and not rec["baseline"]["config"]["station_dow"]
    publish_rest(system)
    r = pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]), n_boot=200)
    # by hand, from the locked files and the published month
    panel = bj.load_panel()
    fc = pd.read_csv(system["forecasts"] / "chi" / "202510" / "champion.csv")
    day = {d.isoformat(): i for i, d in enumerate(panel["days"])}
    y = [panel["Y"][panel["stations"].index(s), day[d]] for s, d in zip(fc["station"], fc["date"], strict=True)]
    assert r["wape_champion"] == pytest.approx((fc["forecast"] - y).abs().sum() / sum(y))
    assert r["wape_champion"] < r["wape_baseline"]  # the planted station-specific weekday profiles
    assert r["cumulative"]["months"] == ["202510"] and r["cumulative"]["decision"] in sk_decisions()
    assert json.loads((system["scores"] / "chi" / "202510.json").read_text())["target_month"] == "202510"


def test_a_forecast_edited_after_lock_is_refused(system):
    pr.lock("chi", str(system["forecasts"]), pr.config_for(["station_dow"]), now=BEFORE)
    path = system["forecasts"] / "chi" / "202510" / "champion.csv"
    path.write_text(path.read_text().replace(".", ",", 1))
    publish_rest(system)
    with pytest.raises(pr.LockError, match="locked hash"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_a_lock_inside_the_target_month_is_refused(system):
    with pytest.raises(pr.LockError, match="already begun"):
        pr.lock("chi", str(system["forecasts"]), pr.config_for([]), now=dt.datetime(2025, 10, 2, tzinfo=dt.UTC))


def test_a_lock_record_dated_inside_the_month_is_refused_at_scoring(system):
    pr.lock("chi", str(system["forecasts"]), pr.config_for([]), now=BEFORE)
    lock = system["forecasts"] / "chi" / "202510" / "lock.json"
    rec = json.loads(lock.read_text())
    rec["created_at"] = "2025-10-05T00:00:00+00:00"
    lock.write_text(json.dumps(rec))
    publish_rest(system)
    with pytest.raises(pr.LockError, match="not a prospective test"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_a_lock_is_never_replaced_and_scoring_waits_for_publication(system):
    pr.lock("chi", str(system["forecasts"]), pr.config_for([]), now=BEFORE)
    with pytest.raises(pr.LockError, match="never replaced"):
        pr.lock("chi", str(system["forecasts"]), pr.config_for(["station_dow"]), now=BEFORE)
    with pytest.raises(pr.LockError, match="not published"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_champion_comes_from_a_run_ledger(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps(dict(champion_history=[dict(promoted="station_dow")])))
    assert pr.champion_from_run(str(tmp_path)) == ["station_dow"]
    with pytest.raises(pr.LockError, match="not on the judge's menu"):
        pr.config_for(["no_such_change"])


def test_champion_from_knowledge_matches_current_champion_or_falls_back_to_baseline(tmp_path):
    kg_path = str(tmp_path / "kg.db")
    assert pr.champion_config_from_knowledge(kg_path, "bikeshare-lab") == dict(bj.BASELINE)
    kg = Knowledge(kg_path, "bikeshare-lab")
    run = kg.begin_run("r1", "judge")
    code_champion = weekend_config()  # a seat-written `code:` idea, not expressible as judge-menu keys
    kg.promote(run, 1, dict(bj.BASELINE), code_champion, "weekend profile", "code:weekend_profile", "test:z")
    resolved = pr.champion_config_from_knowledge(kg_path, "bikeshare-lab")
    assert resolved == code_champion
    assert resolved == Knowledge(kg_path, "bikeshare-lab").current_champion()[0]


def weekend_config():
    from harness.fake_llm import WEEKEND_CODE

    source = WEEKEND_CODE.split("```python\n")[1].split("```")[0]
    return dict(bj.BASELINE, code=[dict(name="weekend_profile", source=source)])


def test_a_challenger_is_locked_with_its_code_and_scored_against_the_baseline(system):
    lead = dict(name="weekend_profile", config=weekend_config(), test="test:x", backtest=dict(point=0.05, lo=0.01))
    menu = dict(name="station_dow", config=pr.config_for(["station_dow"]), test="test:y", backtest={})
    rec = pr.lock("chi", str(system["forecasts"]), pr.config_for([]), now=BEFORE, challengers=[lead, menu])
    assert set(rec["files"]) == {"champion.csv", "baseline.csv", "challenger-weekend_profile.csv",
                                 "challenger-station_dow.csv"}  # fmt: skip
    assert rec["challengers"]["weekend_profile"]["config"]["code"][0]["name"] == "weekend_profile"
    assert rec["alpha_challengers"] == pytest.approx(0.025)
    publish_rest(system)
    r = pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]), n_boot=200)
    ch = r["challengers"]["station_dow"]
    assert ch["alpha"] == pytest.approx(0.025) and ch["wape"] < r["wape_baseline"]  # the planted weekday profiles
    assert ch["decision"] in sk_decisions() and "weekend_profile" in r["challengers"]
    assert set(r["cumulative"]["challengers"]) == {"station_dow", "weekend_profile"}
    assert r["cumulative"]["challengers"]["station_dow"]["months"] == ["202510"]


def test_a_challenger_file_edited_after_lock_is_refused(system):
    lead = dict(name="station_dow", config=pr.config_for(["station_dow"]), test="t", backtest={})
    pr.lock("chi", str(system["forecasts"]), pr.config_for([]), now=BEFORE, challengers=[lead])
    path = system["forecasts"] / "chi" / "202510" / "challenger-station_dow.csv"
    path.write_text(path.read_text().replace(".", ",", 1))
    publish_rest(system)
    with pytest.raises(pr.LockError, match="locked hash"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_challengers_are_the_unpromoted_backtest_leads_read_back_from_their_locked_prereg(tmp_path):
    kg_path, runs = str(tmp_path / "kg.db"), tmp_path / "runs"
    kg = Knowledge(kg_path, "bikeshare-lab")
    run = kg.begin_run("r1", "judge")
    base, lead = dict(bj.BASELINE), weekend_config()

    def record(sid, change, treatment, point, lo, decision="inconclusive", write=True):
        kg.test(run, 1, sid, change=change, change_desc=change, treatment=treatment, comparator=base,
                comparator_desc="baseline", judge="judge", data_key="k", design="B", grade="C",
                decision=dict(point=point, lo=lo, hi=point + 0.05, decision=decision), stage="written")  # fmt: skip
        if write:
            proof = runs / "r1" / "slices" / sid / "proof"
            proof.mkdir(parents=True)
            (proof / "prereg_locked.json").write_text(json.dumps(dict(body=dict(treatment=treatment))))

    record("C1-S1-code_weekend_profile", "code:weekend_profile", lead, 0.06, 0.01)
    record("C2-S1-station_dow", "station_dow", pr.config_for(["station_dow"]), 0.08, -0.01)  # CI crosses zero
    record("C3-S1-holidays", "holidays", pr.config_for(["holidays"]), 0.20, 0.12, decision="supported")
    record("C4-S1-neighbour_pool", "neighbour_pool", pr.config_for(["neighbour_pool"]), 0.04, 0.02, write=False)
    tampered = dict(lead, code=[dict(name="weekend_profile", source="def features(view):\n    return 0\n")])
    record("C5-S1-code_other", "code:other", pr.config_for(["system_trend"]), 0.05, 0.02, write=False)
    proof = runs / "r1" / "slices" / "C5-S1-code_other" / "proof"
    proof.mkdir(parents=True)
    (proof / "prereg_locked.json").write_text(json.dumps(dict(body=dict(treatment=tampered))))
    leads = pr.challengers(kg_path, "bikeshare-lab", str(runs), base)
    assert [c["name"] for c in leads] == ["weekend_profile"]
    assert leads[0]["config"] == lead and leads[0]["backtest"]["lo"] == 0.01


def test_a_judge_digest_mismatch_is_surfaced_in_the_score_not_refused(system, monkeypatch):
    pr.lock("chi", str(system["forecasts"]), pr.config_for(["station_dow"]), now=BEFORE)
    publish_rest(system)
    monkeypatch.setattr(pr, "judge_digest", lambda judge: "a-different-digest")
    r = pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]), n_boot=200)
    assert r["judge_changed"] is True
    assert r["wape_champion"] > 0  # scored anyway: a prospective month cannot be re-run


# ---------------------------------------------------------------------------- tick() and the prospective worktree


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def fake_gh(login):
    """A fake runner: real git, but `gh api user` answers with `login` (or fails, if None) instead of calling out."""
    real_run = subprocess.run

    def run(args, **kwargs):
        if args and args[0] == "gh":
            if login is None:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="gh: not logged in")
            return subprocess.CompletedProcess(args, 0, stdout=login + "\n", stderr="")
        return real_run(args, **kwargs)

    return types.SimpleNamespace(run=run, CompletedProcess=subprocess.CompletedProcess)


@pytest.fixture
def lab(tmp_path):
    """A tiny real git repo (with an `origin` owned by "nblomerus") plus trips published through 202508, for
    `tick()`. The repo is a throwaway under tmp_path -- never the real checkout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "master"], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    (repo / "rigs").mkdir()
    (repo / "rigs" / "bikeshare-lab.json").write_text(
        json.dumps(dict(decision_standards=dict(prospective=dict(sesoi=0.02))))
    )
    (repo / "README.md").write_text("x")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    origin = tmp_path / "nblomerus" / "nightshift.git"
    origin.parent.mkdir()
    _git(["init", "-q", "--bare", str(origin)], tmp_path)
    _git(["remote", "add", "origin", str(origin)], repo)
    _git(["push", "-q", "origin", "master"], repo)
    zips = trip_zips(last="202510")
    data = tmp_path / "data" / "chi"
    ing.ingest("chi", str(data), last="202508", get=stub_get(zips), log=lambda *_: None)
    bj.configure(dict(root=str(data)))
    return dict(repo=repo, zips=zips, data=data, origin=origin)


def alert_log():
    events = []
    return events, lambda kind, message, key=None: events.append((kind, message, key))


def test_tick_locks_a_newly_eligible_month_exactly_once_and_is_idempotent(lab, monkeypatch):
    monkeypatch.setattr(pr, "subprocess", fake_gh("nblomerus"))
    events, alert = alert_log()
    kg_path = str(lab["repo"] / "knowledge" / "bikeshare-lab.db")
    out = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    # 202510's window is still open, so it is locked, not missed; months before the automation existed are never
    # reported as missed (the default floor is FIRST_LOCK_MONTH), so a first tick does not flood the owner
    assert out["locked"] == "202510" and out["scored"] == [] and out["missed"] == []
    assert not any(kind == "missed lock" for kind, _, _ in events)
    worktree = pr.prospective_worktree_path(str(lab["repo"]))
    assert os.path.exists(os.path.join(worktree, "forecasts", "chi", "202510", "lock.json"))
    assert any(kind == "locked" for kind, _, _ in events)
    assert not any(kind == "not pushed" for kind, _, _ in events)  # gh login matches the owner: it pushed

    events.clear()
    out2 = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    assert out2["locked"] is None  # already locked: nothing to do, and cheap
    assert not any(kind == "locked" for kind, _, _ in events)


def test_tick_alerts_missed_lock_once_the_window_has_closed_with_nothing_locked(lab, monkeypatch):
    monkeypatch.setattr(pr, "subprocess", fake_gh("nblomerus"))
    events, alert = alert_log()
    kg_path = str(lab["repo"] / "knowledge" / "bikeshare-lab.db")
    after_close = dt.datetime(2025, 10, 2, tzinfo=dt.UTC)  # 202510's window closed 2025-10-01 with nothing locked
    out = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=after_close,
                  first_month="202501")  # fmt: skip
    assert out["locked"] is None and "202510" in out["missed"]
    missed = [(kind, message, key) for kind, message, key in events if kind == "missed lock"]
    assert any(key == "missed-lock:chi:202510" for _, _, key in missed)
    # the same month is reported again next time (dedup by key is the caller alert()'s own job, not tick's)
    events.clear()
    out2 = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=after_close,
                   first_month="202501")  # fmt: skip
    assert "202510" in out2["missed"]
    assert any(key == "missed-lock:chi:202510" for _, _, key in events if events)


def test_tick_scores_a_locked_month_once_its_target_has_published(lab, monkeypatch):
    monkeypatch.setattr(pr, "subprocess", fake_gh("nblomerus"))
    events, alert = alert_log()
    kg_path = str(lab["repo"] / "knowledge" / "bikeshare-lab.db")
    pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    ing.ingest("chi", str(lab["data"]), get=stub_get(lab["zips"]), log=lambda *_: None)  # 202510 is now published
    bj.configure(dict(root=str(lab["data"])))

    events.clear()
    out = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    assert out["scored"] == ["202510"]
    assert any(kind == "scored" and "202510" in message for kind, message, _ in events)
    worktree = pr.prospective_worktree_path(str(lab["repo"]))
    assert os.path.exists(os.path.join(worktree, "scores", "chi", "202510.json"))

    events.clear()
    out2 = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    assert out2["scored"] == []  # already scored: nothing to do


def test_push_is_skipped_and_alerted_when_the_gh_account_is_not_the_repo_owner(lab, monkeypatch):
    monkeypatch.setattr(pr, "subprocess", fake_gh("someone-else"))
    events, alert = alert_log()
    kg_path = str(lab["repo"] / "knowledge" / "bikeshare-lab.db")
    out = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    assert out["locked"] == "202510"  # the lock itself is unaffected: only the push is skipped
    not_pushed = [m for kind, m, _ in events if kind == "not pushed"]
    assert any("someone-else" in m and "nblomerus" in m for m in not_pushed)
    # nothing reached the remote
    pushed_branches = subprocess.run(
        ["git", "ls-remote", "--heads", str(lab["origin"]), "prospective"], capture_output=True, text=True
    ).stdout
    assert pushed_branches == ""


def test_commit_and_push_pushes_only_when_gh_login_matches_the_repo_owner(lab):
    worktree = pr.ensure_prospective_worktree(str(lab["repo"]))
    os.makedirs(os.path.join(worktree, "forecasts"), exist_ok=True)
    with open(os.path.join(worktree, "forecasts", "x.json"), "w") as f:
        f.write("{}")
    pushed, reason = pr.commit_and_push(
        worktree, str(lab["repo"]), ["forecasts/x.json"], "add x", run=fake_gh("nblomerus").run
    )
    assert pushed and reason is None

    with open(os.path.join(worktree, "forecasts", "y.json"), "w") as f:
        f.write("{}")
    pushed2, reason2 = pr.commit_and_push(
        worktree, str(lab["repo"]), ["forecasts/y.json"], "add y", run=fake_gh("mallory").run
    )
    assert not pushed2 and "mallory" in reason2 and "nblomerus" in reason2


def test_a_commit_that_fails_once_lands_on_the_next_tick(lab, monkeypatch):
    real = fake_gh("nblomerus")
    failed = []

    def run(args, **kwargs):
        if args[:2] == ["git", "commit"] and not failed:
            failed.append(args)
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="fatal: Unable to create index.lock")
        return real.run(args, **kwargs)

    monkeypatch.setattr(pr, "subprocess", types.SimpleNamespace(run=run, CompletedProcess=subprocess.CompletedProcess))
    events, alert = alert_log()
    kg_path = str(lab["repo"] / "knowledge" / "bikeshare-lab.db")
    out = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    assert out["locked"] == "202510" and any("commit failed" in m for k, m, _ in events if k == "not pushed")
    out2 = pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)
    assert out2["locked"] is None and out2["pushed"]  # nothing new to lock, but the pending lock is committed and pushed
    heads = subprocess.run(["git", "ls-remote", "--heads", str(lab["origin"]), "prospective"], capture_output=True,
                           text=True).stdout  # fmt: skip
    assert heads.strip()


def test_a_push_skipped_for_the_wrong_account_goes_out_once_the_owner_is_logged_in(lab, monkeypatch):
    events, alert = alert_log()
    kg_path = str(lab["repo"] / "knowledge" / "bikeshare-lab.db")
    monkeypatch.setattr(pr, "subprocess", fake_gh("someone-else"))
    assert (
        pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)["pushed"] is False
    )
    monkeypatch.setattr(pr, "subprocess", fake_gh("nblomerus"))
    assert pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)["pushed"]
    assert (
        pr.tick("chi", str(lab["repo"]), kg_path, "bikeshare-lab", alert, lambda s: None, now=BEFORE)["pushed"] is False
    )
