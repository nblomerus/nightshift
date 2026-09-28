"""ROADMAP 8e: monthly prospective lock and score (offline, synthetic trips)."""

import datetime as dt
import json

import pandas as pd
import pytest

from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from ops import prospective as pr
from tests.fixtures.bikeshare.synth import stub_get, trip_zips

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
    rec = pr.lock("chi", str(system["forecasts"]), ["yoy_level"], now=BEFORE)
    assert rec["target_month"] == "202510" and rec["data_through"] == "202508"
    assert rec["champion"]["config"]["yoy"] and not rec["baseline"]["config"]["yoy"]
    publish_rest(system)
    r = pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]), n_boot=200)
    # by hand, from the locked files and the published month
    panel = bj.load_panel()
    fc = pd.read_csv(system["forecasts"] / "chi" / "202510" / "champion.csv")
    day = {d.isoformat(): i for i, d in enumerate(panel["days"])}
    y = [panel["Y"][panel["stations"].index(s), day[d]] for s, d in zip(fc["station"], fc["date"], strict=True)]
    assert r["wape_champion"] == pytest.approx((fc["forecast"] - y).abs().sum() / sum(y))
    assert r["wape_champion"] < r["wape_baseline"]  # the planted seasonality: yoy helps two months ahead
    assert json.loads((system["scores"] / "chi" / "202510.json").read_text())["target_month"] == "202510"


def test_a_forecast_edited_after_lock_is_refused(system):
    pr.lock("chi", str(system["forecasts"]), ["yoy_level"], now=BEFORE)
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
        pr.lock("chi", str(system["forecasts"]), ["yoy_level"], now=BEFORE)
    with pytest.raises(pr.LockError, match="not published"):
        pr.score("chi", "202510", str(system["forecasts"]), str(system["scores"]))


def test_champion_comes_from_a_run_ledger(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps(dict(champion_history=[dict(promoted="yoy_level")])))
    assert pr.champion_from_run(str(tmp_path)) == ["yoy_level"]
    with pytest.raises(pr.LockError, match="not on the judge's menu"):
        pr.config_for(["no_such_change"])
