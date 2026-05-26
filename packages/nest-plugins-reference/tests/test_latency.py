# SPDX-License-Identifier: Apache-2.0
"""Unit tests for latency models in nest_plugins_reference.transport.latency."""

from __future__ import annotations

import random
import statistics

import pytest
from nest_core.types import AgentId
from nest_plugins_reference.transport.latency import (
    constant_latency,
    exponential_latency,
    make_latency_model,
    normal_latency,
    pair_matrix_latency,
    uniform_latency,
    with_jitter,
    zero_latency,
)

A1 = AgentId("a1")
A2 = AgentId("a2")
A3 = AgentId("a3")


def _samples(model, n: int = 10_000, seed: int = 1) -> list[float]:
    rng = random.Random(seed)
    return [model(rng, A1, A2) for _ in range(n)]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class TestConstant:
    def test_value(self) -> None:
        rng = random.Random(0)
        m = constant_latency(0.01)
        assert m(rng, A1, A2) == 0.01
        assert m(rng, A1, A3) == 0.01

    def test_zero(self) -> None:
        m = constant_latency(0.0)
        assert m(random.Random(0), A1, A2) == 0.0

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="constant_latency"):
            constant_latency(-1.0)


class TestUniform:
    def test_bounds(self) -> None:
        m = uniform_latency(0.001, 0.005)
        for d in _samples(m, n=500):
            assert 0.001 <= d <= 0.005

    def test_mean_approx(self) -> None:
        m = uniform_latency(0.0, 0.020)
        samples = _samples(m, n=20_000, seed=42)
        # E[U(0, 0.02)] = 0.01.  Allow generous slack for CI noise.
        assert abs(statistics.fmean(samples) - 0.010) < 0.001

    def test_rejects_inverted(self) -> None:
        with pytest.raises(ValueError):
            uniform_latency(0.05, 0.01)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError):
            uniform_latency(-0.01, 0.05)


class TestExponential:
    def test_mean_approx(self) -> None:
        m = exponential_latency(0.02)
        samples = _samples(m, n=20_000, seed=7)
        # E[Exp(1/0.02)] = 0.02.
        assert abs(statistics.fmean(samples) - 0.02) < 0.002

    def test_always_positive(self) -> None:
        m = exponential_latency(0.01)
        assert all(d >= 0.0 for d in _samples(m, n=1_000))

    def test_rejects_non_positive(self) -> None:
        with pytest.raises(ValueError):
            exponential_latency(0.0)
        with pytest.raises(ValueError):
            exponential_latency(-1.0)


class TestNormal:
    def test_clamped_at_min(self) -> None:
        # stddev so large that without clamping we'd see lots of negatives.
        m = normal_latency(0.001, 0.010, min_delay=0.0)
        samples = _samples(m, n=10_000)
        assert all(d >= 0.0 for d in samples)

    def test_min_delay_custom(self) -> None:
        m = normal_latency(0.005, 0.001, min_delay=0.004)
        samples = _samples(m, n=2_000)
        assert all(d >= 0.004 for d in samples)

    def test_rejects_negative_stddev(self) -> None:
        with pytest.raises(ValueError):
            normal_latency(0.01, -0.001)


class TestPairMatrix:
    def test_lookup_hit_and_default(self) -> None:
        m = pair_matrix_latency({("a1", "a2"): 0.05}, default=0.001)
        rng = random.Random(0)
        assert m(rng, A1, A2) == 0.05
        assert m(rng, A1, A3) == 0.001  # falls back to default

    def test_directional(self) -> None:
        m = pair_matrix_latency({("a1", "a2"): 0.05, ("a2", "a1"): 0.01})
        rng = random.Random(0)
        assert m(rng, A1, A2) == 0.05
        assert m(rng, A2, A1) == 0.01


class TestWithJitter:
    def test_within_envelope(self) -> None:
        base = constant_latency(0.010)
        m = with_jitter(base, jitter=0.002)
        for d in _samples(m, n=1_000):
            assert 0.008 <= d <= 0.012

    def test_never_negative(self) -> None:
        # base is zero, jitter could go negative -- must be clamped.
        m = with_jitter(zero_latency(), jitter=0.005)
        assert all(d >= 0.0 for d in _samples(m, n=2_000))


# ---------------------------------------------------------------------------
# make_latency_model factory
# ---------------------------------------------------------------------------


class TestMakeLatencyModel:
    def test_none_is_zero(self) -> None:
        m = make_latency_model(None)
        assert m(random.Random(0), A1, A2) == 0.0

    def test_empty_dict_is_zero(self) -> None:
        m = make_latency_model({})
        assert m(random.Random(0), A1, A2) == 0.0

    def test_constant(self) -> None:
        m = make_latency_model({"kind": "constant", "mean": 0.01})
        assert m(random.Random(0), A1, A2) == 0.01

    def test_uniform(self) -> None:
        m = make_latency_model({"kind": "uniform", "low": 0.0, "high": 0.02})
        for d in _samples(m, n=200):
            assert 0.0 <= d <= 0.02

    def test_exponential(self) -> None:
        m = make_latency_model({"kind": "exponential", "mean": 0.02})
        samples = _samples(m, n=5_000)
        assert abs(statistics.fmean(samples) - 0.02) < 0.005

    def test_normal_with_min_delay(self) -> None:
        m = make_latency_model(
            {"kind": "normal", "mean": 0.005, "stddev": 0.002, "min_delay": 0.001}
        )
        assert all(d >= 0.001 for d in _samples(m, n=2_000))

    def test_pair_matrix_string_keys(self) -> None:
        m = make_latency_model(
            {
                "kind": "pair_matrix",
                "matrix": {"a1,a2": 0.05, "a1,a3": 0.10},
                "default": 0.001,
            }
        )
        rng = random.Random(0)
        assert m(rng, A1, A2) == 0.05
        assert m(rng, A1, A3) == 0.10
        assert m(rng, A2, A3) == 0.001

    def test_pair_matrix_list_keys(self) -> None:
        m = make_latency_model(
            {
                "kind": "pair_matrix",
                "matrix": {("a1", "a2"): 0.05},
                "default": 0.0,
            }
        )
        rng = random.Random(0)
        assert m(rng, A1, A2) == 0.05

    def test_with_jitter_kw(self) -> None:
        m = make_latency_model({"kind": "constant", "mean": 0.010, "jitter": 0.002})
        for d in _samples(m, n=500):
            assert 0.008 <= d <= 0.012

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown latency model kind"):
            make_latency_model({"kind": "moonshine"})

    def test_pair_matrix_bad_key(self) -> None:
        with pytest.raises(ValueError):
            make_latency_model({"kind": "pair_matrix", "matrix": {123: 0.01}})


# ---------------------------------------------------------------------------
# Determinism: same RNG seed -> same sequence
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_uniform_repeatable(self) -> None:
        m = uniform_latency(0.0, 0.020)
        a = [m(random.Random(99), A1, A2) for _ in range(100)]
        b = [m(random.Random(99), A1, A2) for _ in range(100)]
        assert a == b

    def test_factory_repeatable(self) -> None:
        spec = {"kind": "exponential", "mean": 0.02, "jitter": 0.003}
        m1 = make_latency_model(spec)
        m2 = make_latency_model(spec)
        rng_a = random.Random(2024)
        rng_b = random.Random(2024)
        a = [m1(rng_a, A1, A2) for _ in range(200)]
        b = [m2(rng_b, A1, A2) for _ in range(200)]
        assert a == b
