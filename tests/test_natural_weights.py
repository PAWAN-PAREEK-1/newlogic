"""Tests of the in-criteria tilt used by optimization_program/natural_weights.py."""

import numpy as np

from optimization_program.natural_weights import tilt_to_mean


def test_no_change_when_the_target_is_the_simulated_mean():
    q = np.array([0.5, 0.3, 0.2])
    x = np.array([1.0, 2.0, 10.0])
    p, ok = tilt_to_mean(q, x, float(q @ x))
    assert ok
    assert np.allclose(p, q)


def test_reaches_a_higher_and_a_lower_mean():
    q = np.full(5, 0.2)
    x = np.array([0.1, 1.0, 5.0, 50.0, 1000.0])
    for target in (5.0, 600.0):
        p, ok = tilt_to_mean(q, x, target)
        assert ok
        assert abs(p.sum() - 1.0) < 1e-12
        assert abs(float(p @ x) - target) < 1e-6
        assert np.all(p > 0)


def test_narrow_band_far_from_zero():
    """A payout band such as (750, 1500]: payouts barely differ relative to their size."""
    rng = np.random.default_rng(1)
    x = np.sort(rng.uniform(750.2, 1499.9, 400)).round(1)
    q = np.full(x.size, 1.0 / x.size)
    target = float(q @ x) + 0.02
    p, ok = tilt_to_mean(q, x, target)
    assert ok
    assert abs(float(p @ x) - target) < 1e-6


def test_impossible_target_is_reported():
    q = np.array([0.5, 0.5])
    x = np.array([3.0, 3.0])
    _, ok = tilt_to_mean(q, x, 4.0)
    assert not ok
