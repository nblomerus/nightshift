from judges import forecast as fh


def test_leak_canary_fires_on_full_panel_feature_and_not_on_baseline():
    panel = fh.make_panel(0)
    assert fh.leak_canary(panel, dict(fh.BASELINE, series_mean=True))
    assert not fh.leak_canary(panel, fh.BASELINE)


def test_point_in_time_replay_matches_fast_backtest_without_leakage():
    panel = fh.make_panel(1)
    a = fh.evaluate(panel, fh.BASELINE, fh.DEPLOY_ORIGINS[:2])["wape"]
    b = fh.evaluate(panel, fh.BASELINE, fh.DEPLOY_ORIGINS[:2], pit=True)["wape"]
    assert abs(a - b) < 1e-12


def test_known_effect_is_detected_on_average():
    panel = fh.make_panel(2)
    base = fh.evaluate(panel, fh.BASELINE, fh.VAL_ORIGINS)["wape"]
    yoy = fh.evaluate(panel, dict(fh.BASELINE, yoy=True), fh.VAL_ORIGINS)["wape"]
    assert yoy < base * 0.95
