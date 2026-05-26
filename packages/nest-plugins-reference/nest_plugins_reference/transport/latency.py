# SPDX-License-Identifier: Apache-2.0
"""Latency models for the in-memory transport.

A *latency model* is a callable ``(rng, sender, receiver) -> float`` that
returns the per-hop delay (in virtual-time seconds) for one delivery. It
gets the simulator's failure RNG so the resulting trace stays
deterministic under a fixed seed.

The defaults here are deliberately small, pure functions — no I/O, no
state, no global RNG. Plug them into ``Simulator(latency_model=...)`` or
pull them up from a YAML scenario via ``transport_config:``.

Available models:

* ``constant`` — every hop costs ``mean`` seconds.
* ``uniform`` — uniform in ``[low, high]``.
* ``exponential`` — exponential with given ``mean`` (Poisson arrivals).
* ``normal`` — Gaussian ``N(mean, stddev)``, clamped at ``min_delay``.
* ``pair_matrix`` — explicit ``{(from, to): delay}`` lookup with fallback.

Example::

    from nest_plugins_reference.transport.latency import make_latency_model

    model = make_latency_model({"kind": "exponential", "mean": 0.02})
    delay = model(rng, AgentId("a1"), AgentId("a2"))
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from typing import Any, cast

from nest_core.types import AgentId

#: A latency model — pure function from ``(rng, sender, receiver)`` to delay.
LatencyModel = Callable[[random.Random, AgentId, AgentId], float]


# ---------------------------------------------------------------------------
# Primitive models
# ---------------------------------------------------------------------------


def constant_latency(mean: float) -> LatencyModel:
    """Return a model that delivers every hop after exactly ``mean`` seconds.

    Example::

        model = constant_latency(0.01)
        delay = model(rng, AgentId("a"), AgentId("b"))  # always 0.01
    """
    if mean < 0:
        msg = f"constant_latency: mean must be >= 0, got {mean}"
        raise ValueError(msg)

    def _model(_rng: random.Random, _sender: AgentId, _receiver: AgentId) -> float:
        return mean

    return _model


def uniform_latency(low: float, high: float) -> LatencyModel:
    """Return a model uniformly distributed in ``[low, high]``.

    Example::

        model = uniform_latency(0.005, 0.020)
    """
    if low < 0 or high < low:
        msg = f"uniform_latency: require 0 <= low <= high, got low={low}, high={high}"
        raise ValueError(msg)

    def _model(rng: random.Random, _sender: AgentId, _receiver: AgentId) -> float:
        return rng.uniform(low, high)

    return _model


def exponential_latency(mean: float) -> LatencyModel:
    """Return a model with exponential delays of given mean.

    Use this when you want a long-tail latency distribution typical of
    real packet networks.

    Example::

        model = exponential_latency(0.02)
    """
    if mean <= 0:
        msg = f"exponential_latency: mean must be > 0, got {mean}"
        raise ValueError(msg)
    lam = 1.0 / mean

    def _model(rng: random.Random, _sender: AgentId, _receiver: AgentId) -> float:
        return rng.expovariate(lam)

    return _model


def normal_latency(mean: float, stddev: float, min_delay: float = 0.0) -> LatencyModel:
    """Return a model with ``N(mean, stddev)`` delays, clamped to ``[min_delay, ∞)``.

    The clamp is essential — a discrete-event simulator cannot deliver
    in the past.

    Example::

        model = normal_latency(0.01, 0.002)
    """
    if stddev < 0:
        msg = f"normal_latency: stddev must be >= 0, got {stddev}"
        raise ValueError(msg)
    if min_delay < 0:
        msg = f"normal_latency: min_delay must be >= 0, got {min_delay}"
        raise ValueError(msg)

    def _model(rng: random.Random, _sender: AgentId, _receiver: AgentId) -> float:
        return max(min_delay, rng.gauss(mean, stddev))

    return _model


def pair_matrix_latency(
    matrix: Mapping[tuple[str, str], float],
    default: float = 0.0,
) -> LatencyModel:
    """Return a model looking up delays in an explicit ``(from, to)`` matrix.

    Use this to model heterogeneous topologies — fast intra-DC, slow
    inter-DC, etc.  Unlisted pairs fall back to ``default``.

    Example::

        m = pair_matrix_latency({("a", "b"): 0.001, ("a", "c"): 0.050}, default=0.010)
    """
    if default < 0:
        msg = f"pair_matrix_latency: default must be >= 0, got {default}"
        raise ValueError(msg)
    # Materialise once so the lookup is hot.
    table = {(str(s), str(r)): float(d) for (s, r), d in matrix.items()}

    def _model(_rng: random.Random, sender: AgentId, receiver: AgentId) -> float:
        return table.get((str(sender), str(receiver)), default)

    return _model


# ---------------------------------------------------------------------------
# Compositional helpers
# ---------------------------------------------------------------------------


def with_jitter(base: LatencyModel, jitter: float) -> LatencyModel:
    """Wrap a model and add uniform jitter in ``[-jitter, +jitter]``.

    The result is clamped at zero so we never deliver in the past.

    Example::

        model = with_jitter(constant_latency(0.01), jitter=0.002)
    """
    if jitter < 0:
        msg = f"with_jitter: jitter must be >= 0, got {jitter}"
        raise ValueError(msg)

    def _model(rng: random.Random, sender: AgentId, receiver: AgentId) -> float:
        return max(0.0, base(rng, sender, receiver) + rng.uniform(-jitter, jitter))

    return _model


def zero_latency() -> LatencyModel:
    """Return the legacy zero-latency model — every hop delivers immediately.

    This is what NEST does today by default; explicit ``zero_latency()``
    keeps the math obvious when configuration is generated programmatically.

    Example::

        model = zero_latency()
    """

    def _model(_rng: random.Random, _sender: AgentId, _receiver: AgentId) -> float:
        return 0.0

    return _model


# ---------------------------------------------------------------------------
# Factory: build a model from a scenario YAML dict.
# ---------------------------------------------------------------------------


def make_latency_model(spec: Mapping[str, Any] | None) -> LatencyModel:
    """Build a latency model from a scenario-level ``transport_config`` dict.

    Recognised top-level keys:

    * ``kind`` — one of ``constant`` | ``uniform`` | ``exponential`` |
      ``normal`` | ``pair_matrix`` | ``zero`` (default: ``zero``).
    * ``mean`` / ``low`` / ``high`` / ``stddev`` / ``min_delay`` / ``matrix``
      / ``default`` — model-specific parameters.
    * ``jitter`` — optional additional uniform jitter wrapped around the
      base model (after the model is built).

    Returns the legacy zero-latency model when ``spec`` is empty or
    ``None`` so existing scenarios keep their byte-identical traces.

    Example::

        m = make_latency_model({"kind": "exponential", "mean": 0.02, "jitter": 0.005})
    """
    if not spec:
        return zero_latency()

    kind = str(spec.get("kind", "zero")).lower()
    base: LatencyModel

    if kind == "zero":
        base = zero_latency()
    elif kind == "constant":
        base = constant_latency(float(spec["mean"]))
    elif kind == "uniform":
        base = uniform_latency(float(spec["low"]), float(spec["high"]))
    elif kind == "exponential":
        base = exponential_latency(float(spec["mean"]))
    elif kind == "normal":
        base = normal_latency(
            float(spec["mean"]),
            float(spec["stddev"]),
            min_delay=float(spec.get("min_delay", 0.0)),
        )
    elif kind == "pair_matrix":
        raw = spec.get("matrix", {})
        if not isinstance(raw, Mapping):
            msg = "pair_matrix: 'matrix' must be a mapping of '<from>,<to>' to delay"
            raise ValueError(msg)
        raw_items = cast("Mapping[Any, Any]", raw)
        parsed: dict[tuple[str, str], float] = {}
        for key, value in raw_items.items():
            # YAML can't have tuple keys; accept "a,b" strings or [a, b] lists.
            parts: list[str]
            if isinstance(key, str):
                parts = [p.strip() for p in key.split(",")]
            elif (
                isinstance(key, (list, tuple))
                and len(cast("list[Any] | tuple[Any, ...]", key)) == 2
            ):
                key_seq = cast("list[Any] | tuple[Any, ...]", key)
                parts = [str(p) for p in key_seq]
            else:
                msg = f"pair_matrix: unsupported key {key!r}, use '<from>,<to>' or [from, to]"
                raise ValueError(msg)
            if len(parts) != 2:
                msg = f"pair_matrix: key {key!r} must have exactly two parts"
                raise ValueError(msg)
            parsed[(parts[0], parts[1])] = float(value)
        base = pair_matrix_latency(parsed, default=float(spec.get("default", 0.0)))
    else:
        msg = (
            f"Unknown latency model kind={kind!r}. "
            "Expected one of: zero, constant, uniform, exponential, normal, pair_matrix."
        )
        raise ValueError(msg)

    jitter = spec.get("jitter")
    if jitter is not None and float(jitter) > 0:
        base = with_jitter(base, float(jitter))

    return base


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "LatencyModel",
    "constant_latency",
    "exponential_latency",
    "make_latency_model",
    "normal_latency",
    "pair_matrix_latency",
    "uniform_latency",
    "with_jitter",
    "zero_latency",
]
