# SPDX-License-Identifier: Apache-2.0
"""Tests for the EigenTrust reputation plugin.

These tests pin down the algorithm's distinguishing behaviours vs the
naive ``score_average`` plugin:

* A Sybil swarm reporting a colluding peer as "positive" cannot push
  that peer's global trust above a peer endorsed by pre-trusted seeds.
* Recent negative evidence decays old positive evidence under temporal
  decay.
* Self-reports are ignored.
* Pre-trusted seeds bootstrap a sensible global score.
* The implementation is deterministic — same inputs, same scores.
* Repeated ``score`` calls without new reports are cache hits.

Asyncio mode is enabled in the workspace pyproject so ``pytest-asyncio``
picks these up automatically.
"""

from __future__ import annotations

import pytest
from nest_core.types import AgentId, Evidence
from nest_plugins_reference.trust.eigentrust import (
    DEFAULT_SCORE,
    EigenTrust,
)


def _pos(reporter: str, subject: str) -> Evidence:
    return Evidence(
        reporter=AgentId(reporter),
        subject=AgentId(subject),
        kind="positive",
    )


def _neg(reporter: str, subject: str) -> Evidence:
    return Evidence(
        reporter=AgentId(reporter),
        subject=AgentId(subject),
        kind="negative",
    )


class TestBasic:
    """Sanity properties shared with score_average."""

    @pytest.mark.asyncio
    async def test_cold_start_score_is_neutral(self) -> None:
        trust = EigenTrust()
        s = await trust.score(AgentId("nobody"))
        assert s.score == DEFAULT_SCORE
        assert s.confidence == 0.0
        assert s.sample_count == 0

    @pytest.mark.asyncio
    async def test_score_is_bounded(self) -> None:
        trust = EigenTrust()
        # Build a small graph: a1 endorses a2, a3 endorses a2.
        await trust.report(AgentId("a2"), _pos("a1", "a2"))
        await trust.report(AgentId("a2"), _pos("a3", "a2"))
        s = await trust.score(AgentId("a2"))
        assert 0.0 <= s.score <= 1.0
        assert s.sample_count == 2

    @pytest.mark.asyncio
    async def test_negative_report_lowers_score(self) -> None:
        trust = EigenTrust(pre_trusted=[AgentId("seed")])
        # Pre-trusted seed reports good first, then bad — net should be
        # lower than the all-positive case.
        await trust.report(AgentId("a1"), _pos("seed", "a1"))
        good = (await trust.score(AgentId("a1"))).score

        trust2 = EigenTrust(pre_trusted=[AgentId("seed")])
        await trust2.report(AgentId("a1"), _pos("seed", "a1"))
        await trust2.report(AgentId("a1"), _neg("seed", "a1"))
        mixed = (await trust2.score(AgentId("a1"))).score
        assert mixed < good

    @pytest.mark.asyncio
    async def test_unknown_evidence_kind_is_neutral(self) -> None:
        trust = EigenTrust()
        await trust.report(
            AgentId("a1"),
            Evidence(reporter=AgentId("a2"), subject=AgentId("a1"), kind="indifferent"),
        )
        s = await trust.score(AgentId("a1"))
        # Unknown kinds add no signal: agent stays cold-start.
        assert s.sample_count == 0
        assert s.score == DEFAULT_SCORE


class TestEigenProperties:
    """The properties that justify shipping a second trust plugin."""

    @pytest.mark.asyncio
    async def test_sybil_swarm_cannot_outweigh_pre_trusted_seed(self) -> None:
        """A flood of mutual endorsements among unknown peers must not
        beat a single endorsement from a pre-trusted seed.

        Setup: ``seed`` is pre-trusted. ``honest`` gets one positive
        report from ``seed``. ``sybil-target`` gets 100 positive reports
        from 100 unknown ``sybil-N`` peers, who only know each other.
        EigenTrust mixes in the seed's pre-trust mass, so the honest
        peer should still come out ahead.
        """
        trust = EigenTrust(pre_trusted=[AgentId("seed")], alpha=0.2)

        # The seed endorses the honest agent once.
        await trust.report(AgentId("honest"), _pos("seed", "honest"))

        # A Sybil swarm: 100 fake peers that endorse the target and each
        # other heavily. None of them is connected to the seed.
        for k in range(100):
            await trust.report(
                AgentId("sybil-target"),
                _pos(f"sybil-{k}", "sybil-target"),
            )
            # Mutual back-scratching to maximally pump each other up.
            await trust.report(
                AgentId(f"sybil-{k}"),
                _pos("sybil-target", f"sybil-{k}"),
            )

        honest_score = (await trust.score(AgentId("honest"))).score
        sybil_score = (await trust.score(AgentId("sybil-target"))).score
        assert honest_score > sybil_score, (
            f"Sybil clique outranked honest peer: honest={honest_score}, sybil={sybil_score}"
        )

    @pytest.mark.asyncio
    async def test_time_decay_lets_recent_negatives_dominate(self) -> None:
        """Without decay, 10 old positives outweigh 1 recent negative.
        With strong decay, the recent negative wins.
        """
        # No decay: many old positives win.
        no_decay = EigenTrust(pre_trusted=[AgentId("s")], decay_lambda=0.0)
        for _ in range(10):
            await no_decay.report(AgentId("a"), _pos("s", "a"))
        await no_decay.report(AgentId("a"), _neg("s", "a"))
        score_no_decay = (await no_decay.score(AgentId("a"))).score

        # Aggressive decay: recent negative dominates the old positives.
        decay = EigenTrust(pre_trusted=[AgentId("s")], decay_lambda=1.0)
        for _ in range(10):
            await decay.report(AgentId("a"), _pos("s", "a"))
        await decay.report(AgentId("a"), _neg("s", "a"))
        score_decay = (await decay.score(AgentId("a"))).score

        assert score_decay < score_no_decay, (
            f"decay did not lower score: no_decay={score_no_decay}, decay={score_decay}"
        )

    @pytest.mark.asyncio
    async def test_self_reports_are_ignored(self) -> None:
        """An agent cannot endorse itself into the trusted set."""
        trust = EigenTrust()
        for _ in range(100):
            await trust.report(AgentId("liar"), _pos("liar", "liar"))
        # An honest two-party endorsement exists alongside.
        await trust.report(AgentId("good"), _pos("seed", "good"))
        liar_score = (await trust.score(AgentId("liar"))).score
        good_score = (await trust.score(AgentId("good"))).score
        assert liar_score <= good_score

    @pytest.mark.asyncio
    async def test_pre_trusted_seed_gets_positive_score(self) -> None:
        """A seed peer with no incoming reports still gets prior mass."""
        trust = EigenTrust(pre_trusted=[AgentId("seed")])
        # No reports at all. seed should still be > DEFAULT_SCORE-ish
        # once we've observed it.
        await trust.stake(AgentId("seed"), 1)  # registers seed as observed
        # With only one observed agent (seed itself), the global vector
        # collapses to "everyone equal" — we map that to DEFAULT_SCORE.
        # Add another observed agent to break the symmetry.
        await trust.report(AgentId("other"), _pos("seed", "other"))
        s_seed = await trust.score(AgentId("seed"))
        s_other = await trust.score(AgentId("other"))
        # With alpha=0.15, the seed retains the lion's share of mass
        # because it's the only source of pre-trust.
        assert s_seed.score >= s_other.score
        assert s_seed.score > 0.0


class TestDeterminismAndCaching:
    """The plugin must be deterministic and cheap to query."""

    @pytest.mark.asyncio
    async def test_deterministic_across_two_runs(self) -> None:
        reports = [
            _pos("a", "b"),
            _pos("b", "c"),
            _neg("c", "a"),
            _pos("seed", "a"),
        ]
        scores: list[dict[str, float]] = []
        for _ in range(2):
            trust = EigenTrust(pre_trusted=[AgentId("seed")])
            for ev in reports:
                await trust.report(ev.subject, ev)
            run_scores = {
                name: (await trust.score(AgentId(name))).score for name in ("a", "b", "c", "seed")
            }
            scores.append(run_scores)
        assert scores[0] == scores[1]

    @pytest.mark.asyncio
    async def test_score_cache_returns_consistent_values(self) -> None:
        trust = EigenTrust(pre_trusted=[AgentId("seed")])
        await trust.report(AgentId("a"), _pos("seed", "a"))
        s1 = (await trust.score(AgentId("a"))).score
        # Many lookups without new reports must return the same number.
        for _ in range(10):
            assert (await trust.score(AgentId("a"))).score == s1
        # A new report busts the cache.
        await trust.report(AgentId("a"), _neg("seed", "a"))
        s2 = (await trust.score(AgentId("a"))).score
        assert s2 != s1


class TestConfiguration:
    """Validation of constructor parameters."""

    @pytest.mark.asyncio
    async def test_invalid_alpha_raises(self) -> None:
        with pytest.raises(ValueError):
            EigenTrust(alpha=0.0)
        with pytest.raises(ValueError):
            EigenTrust(alpha=1.5)

    @pytest.mark.asyncio
    async def test_invalid_decay_raises(self) -> None:
        with pytest.raises(ValueError):
            EigenTrust(decay_lambda=-0.01)

    @pytest.mark.asyncio
    async def test_invalid_max_iters_raises(self) -> None:
        with pytest.raises(ValueError):
            EigenTrust(max_iters=0)

    @pytest.mark.asyncio
    async def test_stake_raises_confidence(self) -> None:
        trust = EigenTrust(pre_trusted=[AgentId("seed")])
        await trust.report(AgentId("a"), _pos("seed", "a"))
        before = (await trust.score(AgentId("a"))).confidence
        await trust.stake(AgentId("a"), 1000)
        after = (await trust.score(AgentId("a"))).confidence
        assert after > before


class TestPluginRegistry:
    """The plugin must be reachable via the built-in registry name."""

    def test_resolves_via_plugin_registry(self) -> None:
        from nest_core.plugins import PluginRegistry

        cls = PluginRegistry().resolve("trust", "eigentrust")
        # We don't import EigenTrust here directly — that's the point of
        # the registry. Verify by name and protocol.
        from nest_core.layers.trust import Trust

        assert cls.__name__ == "EigenTrust"
        instance = cls()
        assert isinstance(instance, Trust)
