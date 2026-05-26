# SPDX-License-Identifier: Apache-2.0
"""Tests for the EigenTrust plugin.

The reference :class:`ScoreAverageTrust` is naive: it weighs every
reporter equally, so a Sybil clique can promote itself to the top of
the ranking. EigenTrust is supposed to fix exactly that. These tests
exercise both the basic ``Trust`` protocol contract and the
adversarial properties EigenTrust is *meant* to deliver.

Run with::

    uv run pytest packages/nest-plugins-reference/tests/test_eigentrust.py -v
"""

from __future__ import annotations

import pytest
from nest_core.types import AgentId, Claim, Evidence
from nest_plugins_reference.trust.eigentrust import EigenTrust

# ---------------------------------------------------------------------------
# 1. Protocol contract
# ---------------------------------------------------------------------------


class TestEigenTrustContract:
    """Behaviours the ``Trust`` protocol implementations must share."""

    @pytest.mark.asyncio
    async def test_default_score_for_unknown_agent_is_neutral(self) -> None:
        trust = EigenTrust()
        score = await trust.score(AgentId("ghost"))
        # Matches the reference plugin so swapping doesn't shift baselines.
        assert score.score == 0.5
        assert score.confidence == 0.0
        assert score.sample_count == 0

    @pytest.mark.asyncio
    async def test_score_returns_normalised_value_in_unit_interval(self) -> None:
        trust = EigenTrust()
        # Build a tiny network so EigenTrust has something to chew on.
        for _ in range(3):
            await trust.report(
                AgentId("a"),
                Evidence(reporter=AgentId("b"), subject=AgentId("a"), kind="positive"),
            )
        score = await trust.score(AgentId("a"))
        assert 0.0 <= score.score <= 1.0
        assert score.sample_count == 3

    @pytest.mark.asyncio
    async def test_attest_returns_attestation(self) -> None:
        trust = EigenTrust()
        claim = Claim(subject=AgentId("a"), predicate="ok", value="yes")
        att = await trust.attest(AgentId("a"), claim)
        assert att.issuer == AgentId("system")
        assert att.claim == claim

    @pytest.mark.asyncio
    async def test_stake_does_not_raise(self) -> None:
        # ``stake`` is interface scaffolding; we only assert it runs.
        trust = EigenTrust()
        await trust.stake(AgentId("a"), 42)
        await trust.stake(AgentId("a"), 8)

    @pytest.mark.asyncio
    async def test_negative_evidence_lowers_score(self) -> None:
        trust = EigenTrust()
        good, bad = AgentId("good"), AgentId("bad")
        reporter = AgentId("rep")
        await trust.report(good, Evidence(reporter=reporter, subject=good, kind="positive"))
        await trust.report(bad, Evidence(reporter=reporter, subject=bad, kind="negative"))
        s_good = (await trust.score(good)).score
        s_bad = (await trust.score(bad)).score
        assert s_good > s_bad

    @pytest.mark.asyncio
    async def test_rejects_invalid_alpha(self) -> None:
        with pytest.raises(ValueError, match="alpha"):
            EigenTrust(alpha=0.0)
        with pytest.raises(ValueError, match="alpha"):
            EigenTrust(alpha=1.0)


# ---------------------------------------------------------------------------
# 2. Sybil / adversarial properties
# ---------------------------------------------------------------------------


class TestSybilResistance:
    """The whole reason for using EigenTrust over score_average."""

    @pytest.mark.asyncio
    async def test_sybil_clique_cannot_promote_itself(self) -> None:
        """A self-vouching clique with no external trust should rank low.

        Setup: ten Sybil identities all give each other glowing reports.
        One honest agent has a single positive report from a pre-trusted
        seed. Under ``score_average`` the Sybils would tie or beat the
        honest agent; under EigenTrust the honest agent dominates.
        """
        seed = AgentId("seed")
        honest = AgentId("honest")
        sybils = [AgentId(f"sybil-{i}") for i in range(10)]

        trust = EigenTrust(pre_trusted={seed})

        # Seed vouches for honest agent (single, low-volume edge).
        await trust.report(honest, Evidence(reporter=seed, subject=honest, kind="positive"))

        # Sybils circle-vouch each other to the moon (high volume edges).
        for i, src in enumerate(sybils):
            for j, dst in enumerate(sybils):
                if i == j:
                    continue
                for _ in range(5):
                    await trust.report(dst, Evidence(reporter=src, subject=dst, kind="positive"))

        s_honest = (await trust.score(honest)).score
        sybil_scores: list[float] = []
        for s in sybils:
            sybil_scores.append((await trust.score(s)).score)
        assert max(sybil_scores) < s_honest, (
            f"Sybil clique scored max {max(sybil_scores)}, honest scored "
            f"{s_honest} — EigenTrust failed Sybil-resistance property."
        )

    @pytest.mark.asyncio
    async def test_self_vouching_does_not_inflate(self) -> None:
        """An agent reporting itself ``positive`` cannot lift its score
        above an agent reporting another peer."""
        a, b, witness = AgentId("a"), AgentId("b"), AgentId("witness")
        trust = EigenTrust(pre_trusted={witness})

        # ``a`` self-promotes ten times.
        for _ in range(10):
            await trust.report(a, Evidence(reporter=a, subject=a, kind="positive"))
        # ``witness`` (pre-trusted) vouches for ``b`` once.
        await trust.report(b, Evidence(reporter=witness, subject=b, kind="positive"))

        s_a = (await trust.score(a)).score
        s_b = (await trust.score(b)).score
        assert s_b > s_a

    @pytest.mark.asyncio
    async def test_distrusted_reporter_cannot_swing_against_seed(self) -> None:
        """An attacker with no incoming trust should not be able to
        outrank an agent that the pre-trusted seed has vouched for."""
        target = AgentId("target")
        rogue = AgentId("rogue")
        seed = AgentId("seed")
        peer = AgentId("peer")
        trust = EigenTrust(pre_trusted={seed})

        # Seed vouches for target a few times.
        for _ in range(3):
            await trust.report(target, Evidence(reporter=seed, subject=target, kind="positive"))
        # Seed vouches for peer once (so peer enters the graph too).
        await trust.report(peer, Evidence(reporter=seed, subject=peer, kind="positive"))

        # Rogue blasts negative reports against target.
        for _ in range(200):
            await trust.report(target, Evidence(reporter=rogue, subject=target, kind="negative"))
        # Rogue also self-promotes hard.
        for _ in range(200):
            await trust.report(rogue, Evidence(reporter=rogue, subject=rogue, kind="positive"))

        s_target = (await trust.score(target)).score
        s_rogue = (await trust.score(rogue)).score
        assert s_target > s_rogue, (
            f"Untrusted rogue ({s_rogue}) outranked seed-anchored target ({s_target})."
        )


# ---------------------------------------------------------------------------
# 3. Pre-trusted seed behaviour
# ---------------------------------------------------------------------------


class TestPreTrustedSeed:
    @pytest.mark.asyncio
    async def test_seed_propagates_trust_transitively(self) -> None:
        """Seed -> A -> B should give B a non-trivial score."""
        seed = AgentId("seed")
        a, b = AgentId("a"), AgentId("b")
        trust = EigenTrust(pre_trusted={seed})

        for _ in range(3):
            await trust.report(a, Evidence(reporter=seed, subject=a, kind="positive"))
            await trust.report(b, Evidence(reporter=a, subject=b, kind="positive"))

        s_b = (await trust.score(b)).score
        assert s_b > 0.0
        # Transitive trust should still leave the direct neighbour
        # ahead of the second-hop neighbour.
        s_a = (await trust.score(a)).score
        assert s_a >= s_b

    @pytest.mark.asyncio
    async def test_seed_set_unknown_falls_back_to_uniform(self) -> None:
        """If configured seeds never appear in evidence, the algorithm
        should still produce sane scores (uniform fallback)."""
        absent_seed = AgentId("absent")
        a, b = AgentId("a"), AgentId("b")
        trust = EigenTrust(pre_trusted={absent_seed})

        await trust.report(a, Evidence(reporter=b, subject=a, kind="positive"))
        await trust.report(b, Evidence(reporter=a, subject=b, kind="positive"))
        s_a = (await trust.score(a)).score
        s_b = (await trust.score(b)).score
        assert s_a > 0.0
        assert s_b > 0.0


# ---------------------------------------------------------------------------
# 4. Determinism & convergence
# ---------------------------------------------------------------------------


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_evidence_sequence_yields_identical_vector(self) -> None:
        """Determinism is a hard requirement for NEST's reproducibility."""

        async def run() -> dict[AgentId, float]:
            t = EigenTrust(pre_trusted={AgentId("seed")})
            agents = [AgentId(f"a-{i}") for i in range(8)]
            for src in agents:
                for dst in agents:
                    if src == dst:
                        continue
                    await t.report(dst, Evidence(reporter=src, subject=dst, kind="positive"))
            return t.global_trust()

        v1 = await run()
        v2 = await run()
        assert v1.keys() == v2.keys()
        for k in v1:
            # Power iteration on the same sequence -> bit-for-bit identical
            # in CPython (no parallelism, deterministic dict ordering).
            assert v1[k] == v2[k]

    @pytest.mark.asyncio
    async def test_global_trust_sums_to_one(self) -> None:
        trust = EigenTrust()
        for src in (AgentId("a"), AgentId("b"), AgentId("c")):
            for dst in (AgentId("a"), AgentId("b"), AgentId("c")):
                if src == dst:
                    continue
                await trust.report(dst, Evidence(reporter=src, subject=dst, kind="positive"))
        total = sum(trust.global_trust().values())
        assert abs(total - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_converges_within_iteration_cap(self) -> None:
        trust = EigenTrust(alpha=0.15, tolerance=1e-8, max_iterations=64)
        agents = [AgentId(f"a-{i}") for i in range(20)]
        for src in agents:
            for dst in agents:
                if src == dst:
                    continue
                await trust.report(dst, Evidence(reporter=src, subject=dst, kind="positive"))
        _ = trust.global_trust()
        # alpha = 0.15 -> contraction factor 0.85 -> log_0.85(1e-8) ~= 113
        # but with a connected dense graph we hit floating point noise
        # much sooner. 50 is a generous ceiling.
        assert trust.iterations_last_run < 50

    @pytest.mark.asyncio
    async def test_recompute_is_lazy(self) -> None:
        """Many ``score`` calls between two ``report`` calls should
        only trigger one recompute."""
        trust = EigenTrust()
        await trust.report(
            AgentId("a"),
            Evidence(reporter=AgentId("b"), subject=AgentId("a"), kind="positive"),
        )
        # First read forces recompute.
        await trust.score(AgentId("a"))
        n1 = trust.iterations_last_run
        # Subsequent reads with no new evidence: vector reused.
        await trust.score(AgentId("a"))
        await trust.score(AgentId("b"))
        assert trust.iterations_last_run == n1


# ---------------------------------------------------------------------------
# 5. Beats the reference plugin on the headline adversarial property
# ---------------------------------------------------------------------------


class TestBeatsScoreAverage:
    @pytest.mark.asyncio
    async def test_eigentrust_separates_cheater_below_honest(self) -> None:
        """Realistic miniature of the ``reputation`` scenario: with the
        cheater being reported by every honest peer, EigenTrust should
        rank the cheater strictly below every honest agent."""
        seed = AgentId("seed")
        honest = [AgentId(f"honest-{i}") for i in range(6)]
        cheater = AgentId("malicious-0")
        trust = EigenTrust(pre_trusted={seed})

        # Seed vouches for honest agents at the start (bootstrap).
        for h in honest:
            await trust.report(h, Evidence(reporter=seed, subject=h, kind="positive"))

        # Honest agents trade reliably among themselves -> positive reports.
        for src in honest:
            for dst in honest:
                if src == dst:
                    continue
                await trust.report(dst, Evidence(reporter=src, subject=dst, kind="positive"))

        # Cheater tries to game the system: only honest peers report it,
        # and they report it negatively.
        for h in honest:
            await trust.report(cheater, Evidence(reporter=h, subject=cheater, kind="negative"))

        s_cheater = (await trust.score(cheater)).score
        honest_scores: list[float] = []
        for h in honest:
            honest_scores.append((await trust.score(h)).score)
        min_honest = min(honest_scores)
        assert s_cheater < min_honest, (
            f"Cheater scored {s_cheater}, min honest {min_honest} — "
            "EigenTrust failed to separate adversarial agent."
        )
