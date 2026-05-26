# SPDX-License-Identifier: Apache-2.0
"""Tests for the ``sealed_bid`` coordination plugin.

The suite has three groups:

* **Behavioral** tests — basic FIPA lifecycle, error paths, defaults.
* **Mechanism-design** tests — first-price and Vickrey allocation /
  payment rules, reserve price, single-bidder edge cases, ties.
* **Property-based randomized** tests — for a swarm of bidders with
  random valuations, the validator suite passes for both mechanisms.
"""

from __future__ import annotations

import pytest
from nest_core.types import AgentId, Money, Task
from nest_plugins_reference.coordination.sealed_bid import (
    STATUS_COMMITTED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    SealedBidAuction,
    SealedBidAuctionError,
)
from nest_plugins_reference.coordination.validators import (
    check_allocative_efficiency,
    check_first_price_payment,
    check_round,
    check_seller_reserve,
    check_single_winner,
    check_vickrey_payment,
    check_winner_ir,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_swarm(
    n: int, mechanism: str = "vickrey", reserve: int | None = None
) -> tuple[SealedBidAuction, list[SealedBidAuction]]:
    auct = SealedBidAuction(
        AgentId("auctioneer"),
        mechanism=mechanism,  # type: ignore[arg-type]
        reserve=Money(amount=reserve) if reserve is not None else None,
    )
    bidders = [
        SealedBidAuction(
            AgentId(f"b-{i:02d}"),
            mechanism=mechanism,  # type: ignore[arg-type]
        )
        for i in range(n)
    ]
    return auct, bidders


# ---------------------------------------------------------------------------
# Behavioral tests
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_mechanism_is_vickrey(self) -> None:
        coord = SealedBidAuction(AgentId("a1"))
        # Read it back via the round metadata to keep the field private.
        # The mechanism is what propose() stamps onto the round.
        # (We verify in a separate test that propose returns it.)
        assert coord._mechanism == "vickrey"  # type: ignore[reportPrivateUsage] # noqa: SLF001 — internal smoke

    def test_unknown_mechanism_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown mechanism"):
            SealedBidAuction(
                AgentId("a1"),
                mechanism="dutch",  # type: ignore[arg-type]
            )

    def test_negative_reserve_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            SealedBidAuction(AgentId("a1"), reserve=Money(amount=-1))


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_propose_marks_round_open(self) -> None:
        coord = SealedBidAuction(AgentId("a1"))
        rnd = await coord.propose(Task(id="t1", description="job"))
        assert rnd.metadata["status"] == STATUS_OPEN
        assert rnd.metadata["mechanism"] == "vickrey"
        assert rnd.metadata["bids"] == []

    @pytest.mark.asyncio
    async def test_resolve_marks_round_resolved(self) -> None:
        auct, [b1] = _make_swarm(1)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        await auct.resolve(rnd)
        assert rnd.metadata["status"] == STATUS_RESOLVED

    @pytest.mark.asyncio
    async def test_commit_marks_outcome_committed(self) -> None:
        auct, [b1] = _make_swarm(1)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        out = await auct.resolve(rnd)
        await auct.commit(out)
        assert out.metadata["status"] == STATUS_COMMITTED

    @pytest.mark.asyncio
    async def test_participation_after_resolve_rejected(self) -> None:
        auct, [b1, b2] = _make_swarm(2)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        await auct.resolve(rnd)
        with pytest.raises(SealedBidAuctionError, match="cannot bid"):
            await b2.participate(rnd, value=Money(amount=20))

    @pytest.mark.asyncio
    async def test_double_bid_from_same_agent_rejected(self) -> None:
        auct, [b1] = _make_swarm(1)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        with pytest.raises(SealedBidAuctionError, match="already bid"):
            await b1.participate(rnd, value=Money(amount=20))

    @pytest.mark.asyncio
    async def test_negative_bid_rejected(self) -> None:
        auct, [b1] = _make_swarm(1)
        rnd = await auct.propose(Task(id="t1", description="job"))
        with pytest.raises(SealedBidAuctionError, match="non-negative"):
            await b1.participate(rnd, value=Money(amount=-5))

    @pytest.mark.asyncio
    async def test_resolve_is_idempotent(self) -> None:
        auct, [b1, b2] = _make_swarm(2)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=30))
        await b2.participate(rnd, value=Money(amount=50))
        first = await auct.resolve(rnd)
        # Mutating the bids list afterward should not change the
        # outcome of a second resolve call.
        rnd.metadata["bids"].append(  # type: ignore[union-attr]
            {"bidder": "ghost", "amount": 9999}
        )
        second = await auct.resolve(rnd)
        assert first.winner == second.winner
        assert first.metadata["payment"] == second.metadata["payment"]

    @pytest.mark.asyncio
    async def test_resolve_after_commit_rejected(self) -> None:
        auct, [b1] = _make_swarm(1)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        out = await auct.resolve(rnd)
        await auct.commit(out)
        # We have to manually flip the round status to "committed" to
        # exercise the guard — commit() updates the outcome, not the
        # round (the round may live elsewhere). This mirrors what the
        # caller would do when sealing the round in its own state.
        rnd.metadata["status"] = STATUS_COMMITTED
        with pytest.raises(SealedBidAuctionError, match="already committed"):
            await auct.resolve(rnd)


# ---------------------------------------------------------------------------
# Mechanism-design tests
# ---------------------------------------------------------------------------


class TestFirstPrice:
    @pytest.mark.asyncio
    async def test_winner_pays_own_bid(self) -> None:
        auct, [b1, b2, b3] = _make_swarm(3, mechanism="first_price")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=50))
        await b2.participate(rnd, value=Money(amount=100))
        await b3.participate(rnd, value=Money(amount=75))
        out = await auct.resolve(rnd)
        assert out.winner == AgentId("b-01")
        assert out.metadata["payment"] == 100
        assert out.metadata["mechanism"] == "first_price"

    @pytest.mark.asyncio
    async def test_validators_pass(self) -> None:
        auct, [b1, b2, b3] = _make_swarm(3, mechanism="first_price")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=50))
        await b2.participate(rnd, value=Money(amount=100))
        await b3.participate(rnd, value=Money(amount=75))
        out = await auct.resolve(rnd)
        results = check_round(rnd, out)
        for r in results:
            assert r.passed, f"{r.name}: {r.detail}"


class TestVickrey:
    @pytest.mark.asyncio
    async def test_winner_pays_second_highest(self) -> None:
        auct, [b1, b2, b3] = _make_swarm(3, mechanism="vickrey")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=50))
        await b2.participate(rnd, value=Money(amount=100))
        await b3.participate(rnd, value=Money(amount=75))
        out = await auct.resolve(rnd)
        assert out.winner == AgentId("b-01")
        assert out.metadata["payment"] == 75
        assert out.metadata["runner_up"] == "b-02"

    @pytest.mark.asyncio
    async def test_single_bidder_pays_reserve(self) -> None:
        auct, [b1] = _make_swarm(1, mechanism="vickrey", reserve=30)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=100))
        out = await auct.resolve(rnd)
        assert out.winner == AgentId("b-00")
        assert out.metadata["payment"] == 30

    @pytest.mark.asyncio
    async def test_single_bidder_no_reserve_pays_zero(self) -> None:
        auct, [b1] = _make_swarm(1, mechanism="vickrey")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=100))
        out = await auct.resolve(rnd)
        assert out.winner == AgentId("b-00")
        assert out.metadata["payment"] == 0

    @pytest.mark.asyncio
    async def test_reserve_blocks_clearing(self) -> None:
        auct, [b1, b2] = _make_swarm(2, mechanism="vickrey", reserve=200)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=50))
        await b2.participate(rnd, value=Money(amount=100))
        out = await auct.resolve(rnd)
        assert out.winner is None
        assert out.metadata["payment"] == 0
        assert out.metadata["cleared"] is False

    @pytest.mark.asyncio
    async def test_reserve_clamps_payment(self) -> None:
        # Top bid 100 clears reserve 80; second bid 50 < reserve, so
        # the payment should be clamped up to the reserve.
        auct, [b1, b2] = _make_swarm(2, mechanism="vickrey", reserve=80)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=50))
        await b2.participate(rnd, value=Money(amount=100))
        out = await auct.resolve(rnd)
        assert out.winner == AgentId("b-01")
        assert out.metadata["payment"] == 80


class TestTieBreaking:
    @pytest.mark.asyncio
    async def test_lex_min_wins_tie(self) -> None:
        auct, bidders = _make_swarm(3, mechanism="vickrey")
        rnd = await auct.propose(Task(id="t1", description="job"))
        # All three bid the same — winner should be the lex-min id.
        for b in bidders:
            await b.participate(rnd, value=Money(amount=100))
        out = await auct.resolve(rnd)
        assert out.winner == AgentId("b-00")
        # Vickrey on a flat tie: second-highest equals top, so payment
        # equals top. This is correct: a tied second-price auction
        # collapses to a first-price-like payment.
        assert out.metadata["payment"] == 100
        assert set(out.metadata["tied_top_bidders"]) == {
            "b-00",
            "b-01",
            "b-02",
        }

    @pytest.mark.asyncio
    async def test_tie_broken_deterministically_across_runs(self) -> None:
        winners: set[AgentId | None] = set()
        for _ in range(5):
            auct, bidders = _make_swarm(3, mechanism="vickrey")
            rnd = await auct.propose(Task(id="t1", description="job"))
            # Bid in reverse order on purpose — id-based tie-break must
            # ignore arrival order.
            for b in reversed(bidders):
                await b.participate(rnd, value=Money(amount=50))
            out = await auct.resolve(rnd)
            winners.add(out.winner)
        assert winners == {AgentId("b-00")}


class TestEmpty:
    @pytest.mark.asyncio
    async def test_no_bidders(self) -> None:
        coord = SealedBidAuction(AgentId("a1"))
        rnd = await coord.propose(Task(id="t1", description="job"))
        out = await coord.resolve(rnd)
        assert out.winner is None
        assert out.metadata["payment"] == 0
        assert out.metadata["cleared"] is False
        assert out.metadata["num_bidders"] == 0
        for r in check_round(rnd, out):
            assert r.passed, f"{r.name}: {r.detail}"


# ---------------------------------------------------------------------------
# Validator-level (mechanism-design) tests
# ---------------------------------------------------------------------------


class TestValidators:
    @pytest.mark.asyncio
    async def test_winner_ir_holds_under_vickrey(self) -> None:
        # Vickrey is IR for the winner by construction (payment <=
        # winning bid) — assert it explicitly here.
        auct, [b1, b2, b3] = _make_swarm(3, mechanism="vickrey")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        await b2.participate(rnd, value=Money(amount=20))
        await b3.participate(rnd, value=Money(amount=30))
        out = await auct.resolve(rnd)
        r = check_winner_ir(rnd, out)
        assert r.passed, r.detail

    @pytest.mark.asyncio
    async def test_allocative_efficiency_with_reserve_block(self) -> None:
        auct, [b1, b2] = _make_swarm(2, mechanism="first_price", reserve=500)
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        await b2.participate(rnd, value=Money(amount=20))
        out = await auct.resolve(rnd)
        # No allocation, but allocative efficiency check must pass —
        # this is the "seller withholds when reserve unmet" case.
        r = check_allocative_efficiency(rnd, out)
        assert r.passed, r.detail
        r2 = check_seller_reserve(rnd, out)
        assert r2.passed, r2.detail

    @pytest.mark.asyncio
    async def test_vickrey_validator_skipped_under_first_price(self) -> None:
        auct, [b1] = _make_swarm(1, mechanism="first_price")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        out = await auct.resolve(rnd)
        r = check_vickrey_payment(rnd, out)
        assert r.passed
        assert "not vickrey" in r.detail

    @pytest.mark.asyncio
    async def test_first_price_validator_skipped_under_vickrey(self) -> None:
        auct, [b1] = _make_swarm(1, mechanism="vickrey")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        out = await auct.resolve(rnd)
        r = check_first_price_payment(rnd, out)
        assert r.passed
        assert "not first_price" in r.detail

    @pytest.mark.asyncio
    async def test_single_winner_with_ties(self) -> None:
        auct, [b1, b2] = _make_swarm(2, mechanism="vickrey")
        rnd = await auct.propose(Task(id="t1", description="job"))
        await b1.participate(rnd, value=Money(amount=10))
        await b2.participate(rnd, value=Money(amount=10))
        out = await auct.resolve(rnd)
        r = check_single_winner(rnd, out)
        assert r.passed, r.detail


# ---------------------------------------------------------------------------
# Property-based randomized sweep
# ---------------------------------------------------------------------------


class TestRandomSwarms:
    """Randomized sweep: validate properties hold across many bidder
    populations, valuations, and reserve prices.

    Bounded with a fixed seed so the test is deterministic.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mechanism", ["vickrey", "first_price"])
    async def test_validators_hold_for_random_swarms(self, mechanism: str) -> None:
        import random

        rng = random.Random(20260526)
        for trial in range(50):
            n = rng.randint(0, 15)
            reserve = rng.choice([None, 0, 5, 25, 80])
            auct, bidders = _make_swarm(n, mechanism=mechanism, reserve=reserve)
            rnd = await auct.propose(Task(id=f"t-{trial}", description="job"))
            for b in bidders:
                await b.participate(rnd, value=Money(amount=rng.randint(0, 100)))
            out = await auct.resolve(rnd)
            for r in check_round(rnd, out):
                assert r.passed, f"trial={trial} mechanism={mechanism} {r.name}: {r.detail}"


# ---------------------------------------------------------------------------
# Plugin registry wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def test_sealed_bid_is_resolvable(self) -> None:
        from nest_core.plugins import PluginRegistry

        cls = PluginRegistry().resolve("coordination", "sealed_bid")
        assert cls is SealedBidAuction

    def test_sealed_bid_listed(self) -> None:
        from nest_core.plugins import PluginRegistry

        plugins = PluginRegistry().list_plugins("coordination")
        assert ("coordination", "sealed_bid") in plugins
        assert ("coordination", "contract_net") in plugins
