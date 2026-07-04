# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests for the receipt_reputation scenario + adversarial validator.

The headline assertions are the adversarial proof the charter requires:

* the ``receipt_reputation`` validator **FAILS** under ``trust: score_average``
  (the collusion ring is rewarded), and
* **PASSES** under ``trust: agent_receipts`` (the ring is severed to ~0, honest
  agents retained),

plus a byte-level determinism check (same seed -> identical trace sha256).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig
from nest_core.validators import validate_trace

_SCENARIO_YAML = (
    Path(__file__).parent.parent.parent.parent / "scenarios" / "receipt_reputation.yaml"
)


def _config(trust: str, trace: Path, seed: int | None = None) -> ScenarioConfig:
    """Load the scenario YAML, override the trust plugin, seed, and trace path."""
    config = ScenarioConfig.from_yaml(_SCENARIO_YAML)
    config.layers.trust = trust
    config.output.trace = str(trace)
    if seed is not None:
        config.seed = seed
    return config


def _results(trace: Path) -> dict[str, bool]:
    return {r.name: r.passed for r in validate_trace(trace, "receipt_reputation")}


class TestAdversarialProof:
    # Seed-bank robustness: the leaderboard re-runs under multiple seeds, so the
    # adversarial proof must hold across the bank, not just the default seed.
    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", [1, 7, 42, 123, 9999])
    async def test_validator_passes_under_agent_receipts(self, tmp_path: Path, seed: int) -> None:
        trace = tmp_path / f"ours_{seed}.jsonl"
        await ScenarioRunner(_config("agent_receipts", trace, seed=seed)).run()
        results = _results(trace)
        assert results["receipt_reputation_ring_severed"] is True
        assert results["receipt_reputation_honest_confidence"] is True

    @pytest.mark.asyncio
    async def test_validator_fails_under_score_average(self, tmp_path: Path) -> None:
        trace = tmp_path / "baseline.jsonl"
        await ScenarioRunner(_config("score_average", trace)).run()
        results = _results(trace)
        # The whole point: the naive baseline rewards the wash-trading ring.
        assert results["receipt_reputation_ring_severed"] is False
        assert results["receipt_reputation_honest_confidence"] is False


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_seed_identical_trace(self, tmp_path: Path) -> None:
        t1 = tmp_path / "run1.jsonl"
        t2 = tmp_path / "run2.jsonl"
        await ScenarioRunner(_config("agent_receipts", t1)).run()
        await ScenarioRunner(_config("agent_receipts", t2)).run()
        h1 = hashlib.sha256(t1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(t2.read_bytes()).hexdigest()
        assert h1 == h2


class TestScenarioShape:
    @pytest.mark.asyncio
    async def test_emits_score_lines_for_every_population(self, tmp_path: Path) -> None:
        trace = tmp_path / "shape.jsonl"
        await ScenarioRunner(_config("agent_receipts", trace)).run()
        text = trace.read_text()
        assert "score:honest-0:" in text
        assert "score:ring-0:" in text
        assert "score:byz-0:" in text

    @pytest.mark.asyncio
    async def test_byzantine_uncorroborated_scores_zero(self, tmp_path: Path) -> None:
        """Byzantine receipts have broken co-signatures, so they earn nothing."""
        trace = tmp_path / "byz.jsonl"
        await ScenarioRunner(_config("agent_receipts", trace)).run()
        # the byzantine agent's emitted score must be 0 under our plugin
        line = next(ln for ln in trace.read_text().splitlines() if "score:byz-0:" in ln)
        # ...:score:byz-0:<score>:<conf>:byz...
        body = line.split("score:byz-0:", 1)[1]
        score = float(body.split(":")[0])
        assert score == 0.0
