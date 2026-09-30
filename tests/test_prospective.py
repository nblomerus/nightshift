"""ROADMAP 8e: monthly prospective lock and score (offline, synthetic trips)."""

import datetime as dt
import json

import pandas as pd
import pytest

from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from ops import prospective as pr
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
    rec = pr.lock("chi", str(system["forecasts"]), ["station_dow", "holidays"], now=BEFORE)
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
    pr.lock("chi", str(system["forecasts"]), ["station_dow"], now=BEFORE)
    path = system["forecasts"] / "chi" / "202510" / "champion.csv"
    path.write_text(path.read_text().replace(".", ",", 1))
    publish_rest(system)
    with pytest.raises(pr.LockError, match="locked hash"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_a_lock_inside_the_target_month_is_refused(system):
    with pytest.raises(pr.LockError, match="already begun"):
        pr.lock("chi", str(system["forecasts"]), [], now=dt.datetime(2025, 10, 2, tzinfo=dt.UTC))


def test_a_lock_record_dated_inside_the_month_is_refused_at_scoring(system):
    pr.lock("chi", str(system["forecasts"]), [], now=BEFORE)
    lock = system["forecasts"] / "chi" / "202510" / "lock.json"
    rec = json.loads(lock.read_text())
    rec["created_at"] = "2025-10-05T00:00:00+00:00"
    lock.write_text(json.dumps(rec))
    publish_rest(system)
    with pytest.raises(pr.LockError, match="not a prospective test"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_a_lock_is_never_replaced_and_scoring_waits_for_publication(system):
    pr.lock("chi", str(system["forecasts"]), [], now=BEFORE)
    with pytest.raises(pr.LockError, match="never replaced"):
        pr.lock("chi", str(system["forecasts"]), ["station_dow"], now=BEFORE)
    with pytest.raises(pr.LockError, match="not published"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_champion_comes_from_a_run_ledger(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps(dict(champion_history=[dict(promoted="station_dow")])))
    assert pr.champion_from_run(str(tmp_path)) == ["station_dow"]
    with pytest.raises(pr.LockError, match="not on the judge's menu"):
        pr.config_for(["no_such_change"])


def weekend_config():
    from harness.fake_llm import WEEKEND_CODE

    source = WEEKEND_CODE.split("```python\n")[1].split("```")[0]
    return dict(bj.BASELINE, code=[dict(name="weekend_profile", source=source)])


def test_a_challenger_is_locked_with_its_code_and_scored_against_the_baseline(system):
    lead = dict(name="weekend_profile", config=weekend_config(), test="test:x", backtest=dict(point=0.05, lo=0.01))
    menu = dict(name="station_dow", config=pr.config_for(["station_dow"]), test="test:y", backtest={})
    rec = pr.lock("chi", str(system["forecasts"]), [], now=BEFORE, challengers=[lead, menu])
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
    pr.lock("chi", str(system["forecasts"]), [], now=BEFORE, challengers=[lead])
    path = system["forecasts"] / "chi" / "202510" / "challenger-station_dow.csv"
    path.write_text(path.read_text().replace(".", ",", 1))
    publish_rest(system)
    with pytest.raises(pr.LockError, match="locked hash"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_challengers_are_the_unpromoted_backtest_leads_read_back_from_their_locked_prereg(tmp_path):
    from state.knowledge import Knowledge

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
