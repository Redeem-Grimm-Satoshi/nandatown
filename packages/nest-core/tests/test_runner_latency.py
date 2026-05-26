# SPDX-License-Identifier: Apache-2.0
"""End-to-end: scenario YAML ``transport_config`` -> measurable latency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from nest_core.runner import (
    ScenarioRunner,
    _build_latency_model_from_config,  # pyright: ignore[reportPrivateUsage]
)
from nest_core.scenario import ScenarioConfig


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _mean_latency(events: list[dict[str, Any]]) -> float:
    sends: dict[str, float] = {}
    diffs: list[float] = []
    for ev in events:
        cid = ev.get("corr", "")
        if not cid:
            continue
        if ev["kind"] == "send":
            sends[cid] = ev["ts"]
        elif ev["kind"] == "receive" and cid in sends:
            diffs.append(ev["ts"] - sends[cid])
    return sum(diffs) / len(diffs) if diffs else 0.0


# ---------------------------------------------------------------------------
# Helper: minimal marketplace config
# ---------------------------------------------------------------------------


def _mk_config(
    tmp_path: Path,
    transport_config: dict[str, Any] | None = None,
) -> ScenarioConfig:
    data: dict[str, Any] = {
        "name": "latency-rt-test",
        "seed": 7,
        "agents": {
            "count": 10,
            "roles": [
                {"name": "buyer", "count": 5},
                {"name": "seller", "count": 5},
            ],
        },
        "task": {"type": "marketplace", "config": {"rounds": 3}},
        "duration": "ticks: 4000",
        "output": {"trace": str(tmp_path / "trace.jsonl")},
    }
    if transport_config is not None:
        data["transport_config"] = transport_config
    return ScenarioConfig.from_dict(data)


# ---------------------------------------------------------------------------
# Backward compatibility: no transport_config -> zero latency
# ---------------------------------------------------------------------------


class TestBackwardCompatible:
    @pytest.mark.asyncio
    async def test_no_transport_config_keeps_zero_latency(self, tmp_path: Path) -> None:
        config = _mk_config(tmp_path)
        result = await ScenarioRunner(config).run()
        assert _mean_latency(_events(result)) == 0.0

    @pytest.mark.asyncio
    async def test_empty_transport_config_keeps_zero_latency(self, tmp_path: Path) -> None:
        config = _mk_config(tmp_path, transport_config={})
        result = await ScenarioRunner(config).run()
        assert _mean_latency(_events(result)) == 0.0


# ---------------------------------------------------------------------------
# Constant latency through the YAML surface
# ---------------------------------------------------------------------------


class TestConstantLatencyViaYaml:
    @pytest.mark.asyncio
    async def test_traces_show_nonzero_latency(self, tmp_path: Path) -> None:
        config = _mk_config(
            tmp_path,
            transport_config={"kind": "constant", "mean": 0.005},
        )
        result = await ScenarioRunner(config).run()
        events = _events(result)
        # Every hop is 0.005, so mean send->receive latency == 0.005.
        assert _mean_latency(events) == pytest.approx(0.005, abs=1e-9)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Deterministic with a stochastic latency model
# ---------------------------------------------------------------------------


class TestDeterministic:
    @pytest.mark.asyncio
    async def test_same_seed_same_trace(self, tmp_path: Path) -> None:
        blobs: list[str] = []
        for run in range(2):
            sub = tmp_path / f"r{run}"
            sub.mkdir()
            config = _mk_config(
                sub,
                transport_config={"kind": "exponential", "mean": 0.01, "jitter": 0.002},
            )
            result = await ScenarioRunner(config).run()
            blobs.append(result.read_text())
        assert blobs[0] == blobs[1]
        assert len(blobs[0]) > 0


# ---------------------------------------------------------------------------
# Latency block nested under ``transport_config.latency`` is also accepted
# ---------------------------------------------------------------------------


class TestNestedLatencyBlock:
    @pytest.mark.asyncio
    async def test_nested_latency_block(self, tmp_path: Path) -> None:
        config = _mk_config(
            tmp_path,
            transport_config={"latency": {"kind": "constant", "mean": 0.002}},
        )
        result = await ScenarioRunner(config).run()
        assert _mean_latency(_events(result)) == pytest.approx(0.002, abs=1e-9)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Helper builds a model (or None) correctly
# ---------------------------------------------------------------------------


class TestBuildLatencyModelHelper:
    def test_none_returns_none(self) -> None:
        assert _build_latency_model_from_config(None) is None

    def test_empty_returns_none(self) -> None:
        assert _build_latency_model_from_config({}) is None

    def test_kind_returns_callable(self) -> None:
        m = _build_latency_model_from_config({"kind": "constant", "mean": 0.01})
        assert callable(m)
