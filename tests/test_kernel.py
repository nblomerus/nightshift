import dataclasses as dc

import numpy as np
import pytest

from science import kernel as sk


def _pre(**kw):
    base = dict(
        hid="H1",
        statement="s",
        estimand="e",
        treatment={"a": 1},
        comparator={"a": 0},
        primary_metric="WAPE",
        unit="series",
        sesoi=0.01,
    )
    base.update(kw)
    return sk.Preregistration(**base)


def test_lock_and_verify_detects_tampering():
    p = _pre().lock()
    assert p.verify()
    tampered = dc.replace(p, sesoi=0.001)  # edit after locking, digest kept
    assert not tampered.verify()


def test_run_test_refuses_unlocked_prereg():
    with pytest.raises(AssertionError):
        sk.run_test(_pre(), lambda g: None, np.random.default_rng(0))


@pytest.mark.parametrize(
    "est,expected",
    [
        (dict(point=0.03, lo=0.01, hi=0.05), "supported"),
        (dict(point=0.005, lo=0.001, hi=0.009), "no_effect"),  # real but below SESOI, CI inside +-SESOI
        (dict(point=-0.03, lo=-0.05, hi=-0.01), "harmful"),
        (dict(point=0.015, lo=-0.01, hi=0.04), "inconclusive"),
        (dict(point=0.008, lo=0.001, hi=0.015), "inconclusive"),  # CI > 0 but point < SESOI and CI crosses SESOI
    ],
)
def test_decision_rule(est, expected):
    assert sk.decide(est, 0.01) == expected


def test_paired_effect_zero_for_identical_arms():
    rng = np.random.default_rng(0)
    e = np.abs(rng.normal(size=(50, 8)))
    est = sk.paired_effect(e, e, 0.05, 200, rng)
    assert est["point"] == 0 and est["lo"] == 0 and est["hi"] == 0


def test_two_way_bootstrap_is_wider_than_units_only_with_time_shocks():
    rng = np.random.default_rng(1)
    shock = rng.normal(0, 0.3, 8)  # effect varies by origin (time)
    c = np.abs(rng.normal(10, 1, (200, 8)))
    t = c * (1 - 0.02 - shock[None, :] * 0.05)
    w1 = sk.paired_effect(t, c, 0.05, 500, np.random.default_rng(2), two_way=False)
    w2 = sk.paired_effect(t, c, 0.05, 500, np.random.default_rng(2), two_way=True)
    assert (w2["hi"] - w2["lo"]) > (w1["hi"] - w1["lo"])


def test_fdr_ledger_alpha_shrinks_without_discoveries():
    led = sk.FDRLedger(alpha=0.05)
    a1 = led.next_alpha()
    led.record(_pre().lock(), a1, dict(point=0, lo=0, hi=0), "inconclusive")
    assert led.next_alpha() < a1


def test_evidence_grades():
    assert sk.evidence_grade("supported", True, 0, True).startswith("A")
    assert sk.evidence_grade("supported", False, 0, True).startswith("B")
    assert sk.evidence_grade("supported", True, 1, True).startswith("C")
    assert sk.evidence_grade("supported", True, 0, False).startswith("D")


def test_a_grade_says_whether_replication_is_pending_or_failed_and_negatives_replicate():
    from agents.common import replication_status

    assert sk.evidence_grade("supported", None, 0, True) == "B: supported, awaiting replication"
    assert sk.evidence_grade("supported", False, 0, True) == "B: supported, not replicated"
    assert sk.evidence_grade("no_effect", True, 0, True) == "A: negative result, replicated"
    assert replication_status("no_effect", None) is None
    assert replication_status("no_effect", {"decision": "no_effect", "same_treatment": True}) is True
    assert replication_status("supported", {"decision": "no_effect", "same_treatment": True}) is False
    assert replication_status("supported", {"decision": "supported", "same_treatment": False}) is False


def test_judge_digest_is_part_of_the_locked_body():
    a, b = _pre(judge_digest="aaa").lock(), _pre(judge_digest="bbb").lock()
    assert a.verify() and b.verify() and a.digest != b.digest
    assert not dc.replace(a, judge_digest="bbb").verify()


def test_a_rig_that_seeks_any_reliable_improvement_promotes_small_real_gains():
    est = dict(point=0.055, lo=0.041, hi=0.08)  # a real, tightly measured +5.5 %
    assert sk.decide(est, 0.10) == "no_effect"  # under a 10 % SESOI it is "too small to matter"
    assert sk.decide(est, 0.05, 0.0) == "supported"  # seeking any reliable improvement: adopt it (after replication)
    assert sk.decide(dict(point=0.01, lo=-0.01, hi=0.03), 0.05, 0.0) == "no_effect"  # SESOI still bounds "no effect"
    assert sk.decide(dict(point=0.02, lo=-0.04, hi=0.08), 0.05, 0.0) == "inconclusive"


def test_min_effect_is_locked_into_new_preregs_without_changing_old_digests():
    base = dict(hid="h", statement="s", estimand="e", treatment={"a": 1}, comparator={}, primary_metric="m", unit="u",
                sesoi=0.05)  # fmt: skip
    old = sk.Preregistration(**base).lock()
    assert "min_effect" not in old._body()  # a prereg from before the field: same body, same digest
    assert sk.Preregistration(**old._body(), digest=old.digest).verify()
    new = sk.Preregistration(**base, min_effect=0.0).lock()
    assert new._body()["min_effect"] == 0.0 and new.digest != old.digest
    assert not __import__("dataclasses").replace(new, min_effect=0.05).verify()  # tampering after lock is caught
