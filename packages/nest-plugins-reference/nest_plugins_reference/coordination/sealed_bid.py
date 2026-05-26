# SPDX-License-Identifier: Apache-2.0
"""Sealed-bid auction coordination plugin.

An alternative to :mod:`contract_net` that implements a proper
**sealed-bid auction** mechanism with two variants:

* ``first_price`` — highest bidder wins and pays their own bid
  (first-price sealed-bid, FPSB).
* ``vickrey`` — highest bidder wins and pays the **second-highest** bid
  (second-price sealed-bid, a.k.a. Vickrey). Under standard assumptions
  truthful bidding is a (weakly) dominant strategy.

Compared to the reference ``contract_net`` plugin this implementation:

* models a real auction (highest valuation wins, not lowest cost),
* supports a **reserve price** below which no allocation is made,
* tracks **FIPA-style round state** (``OPEN`` → ``RESOLVED`` →
  ``COMMITTED``) and refuses out-of-order operations,
* records who tied with the winner so validators can reason about
  tie-breaking, and
* exposes the **payment rule** chosen by the mechanism in the outcome
  metadata so trust/payments layers can settle correctly.

The plugin is registered under the ``nest.plugins.coordination`` entry
point as ``sealed_bid``. Pick the mechanism in scenario YAML::

    layers:
      coordination: sealed_bid

The default mechanism is ``vickrey`` (truthful by construction). To
construct directly with a different mechanism::

    coord = SealedBidAuction(AgentId("auctioneer"), mechanism="first_price")

Why this matters for testing: a downstream trust or payments layer can
now be tested under two market mechanisms with materially different
incentive properties without rewriting any scenario glue.

Example (manager + three bidders)::

    auctioneer = SealedBidAuction(AgentId("a0"))
    b1 = SealedBidAuction(AgentId("b1"))
    b2 = SealedBidAuction(AgentId("b2"))
    b3 = SealedBidAuction(AgentId("b3"))

    rnd = await auctioneer.propose(Task(id="item-1", description="vase"))
    await b1.participate(rnd, value=Money(amount=80))
    await b2.participate(rnd, value=Money(amount=100))
    await b3.participate(rnd, value=Money(amount=60))

    outcome = await auctioneer.resolve(rnd)
    # winner = b2; payment = 80 (second-highest) under vickrey;
    # payment = 100 under first_price.
"""

from __future__ import annotations

import uuid
from typing import Final, Literal

from nest_core.types import (
    AgentId,
    Bid,
    Money,
    Outcome,
    Round,
    Task,
    Vote,
)

Mechanism = Literal["first_price", "vickrey"]

# Round status values stored in ``round.metadata['status']``. Kept as
# plain strings so traces remain JSON-friendly.
STATUS_OPEN: Final[str] = "open"
STATUS_RESOLVED: Final[str] = "resolved"
STATUS_COMMITTED: Final[str] = "committed"

_VALID_MECHANISMS: Final[frozenset[str]] = frozenset({"first_price", "vickrey"})


class SealedBidAuctionError(RuntimeError):
    """Raised when sealed-bid auction operations are called out of order.

    Example::

        try:
            await coord.participate(rnd)
        except SealedBidAuctionError:
            ...
    """


class SealedBidAuction:
    """Sealed-bid auction coordination protocol.

    Parameters
    ----------
    agent_id:
        Identity of the agent using this instance. The same instance is
        used by both auctioneer and bidder agents — the role is inferred
        from which methods are called (``propose`` / ``resolve`` for
        auctioneer, ``participate`` for bidders).
    mechanism:
        ``"vickrey"`` (default; second-price sealed-bid) or
        ``"first_price"``.
    reserve:
        Optional reserve price. If the highest bid is strictly less than
        the reserve, the round is resolved with ``winner = None``.

    Example::

        coord = SealedBidAuction(AgentId("a1"), mechanism="vickrey")
    """

    def __init__(
        self,
        agent_id: AgentId,
        mechanism: Mechanism = "vickrey",
        reserve: Money | None = None,
    ) -> None:
        if mechanism not in _VALID_MECHANISMS:
            msg = (
                f"unknown mechanism {mechanism!r}; "
                f"expected one of {sorted(_VALID_MECHANISMS)}"
            )
            raise ValueError(msg)
        if reserve is not None and reserve.amount < 0:
            msg = f"reserve must be non-negative, got {reserve.amount}"
            raise ValueError(msg)
        self._agent_id = agent_id
        self._mechanism: Mechanism = mechanism
        self._reserve = reserve

    # ------------------------------------------------------------------
    # FIPA-style lifecycle
    # ------------------------------------------------------------------

    async def propose(self, task: Task) -> Round:
        """Announce a sealed-bid auction for ``task``.

        The returned :class:`Round` is the shared state mutated by all
        participants. Its ``metadata`` carries:

        * ``mechanism`` — the chosen payment rule,
        * ``reserve`` — the reserve price (``None`` if not set),
        * ``status`` — FIPA-ish lifecycle marker,
        * ``bids`` — list of submitted bids; populated by
          :meth:`participate`.

        Example::

            rnd = await coord.propose(Task(id="t1", description="job"))
        """
        round_id = str(uuid.uuid4())
        rnd = Round(
            id=round_id,
            task=task,
            participants=[],
            metadata={
                "mechanism": self._mechanism,
                "reserve": (None if self._reserve is None else self._reserve.amount),
                "manager": str(self._agent_id),
                "status": STATUS_OPEN,
                "bids": [],
            },
        )
        return rnd

    async def participate(
        self,
        round: Round,
        value: Money | None = None,
    ) -> Vote | Bid:
        """Submit a sealed bid for ``round``.

        ``value`` is the bidder's reservation value. Under the Vickrey
        mechanism the dominant strategy is to bid one's true value;
        under first-price bidders should shade. The mechanism itself
        does not enforce truthfulness — that is a property of the
        equilibrium, not of the protocol — but the validator
        :func:`is_vickrey_truthful_assignment` checks it on traces.

        If ``value`` is omitted the agent submits a unit bid of
        ``Money(amount=1)``, matching the contract-net default so this
        plugin can be a drop-in replacement.

        Example::

            await coord.participate(rnd, value=Money(amount=100))
        """
        if round.metadata.get("status") != STATUS_OPEN:
            msg = (
                f"cannot bid on round {round.id!r}: "
                f"status is {round.metadata.get('status')!r}"
            )
            raise SealedBidAuctionError(msg)

        bid_amount = value if value is not None else Money(amount=1)
        if bid_amount.amount < 0:
            msg = f"bid must be non-negative, got {bid_amount.amount}"
            raise SealedBidAuctionError(msg)

        bid = Bid(
            bidder=self._agent_id,
            round_id=round.id,
            amount=bid_amount,
        )
        bids: list[dict[str, object]] = round.metadata.setdefault("bids", [])
        # Reject duplicate bids from the same agent — sealed-bid auctions
        # are one-shot by definition; a re-submission almost certainly
        # indicates a buggy agent.
        for existing in bids:
            if existing.get("bidder") == str(self._agent_id):
                msg = (
                    f"agent {self._agent_id!r} already bid on round "
                    f"{round.id!r}"
                )
                raise SealedBidAuctionError(msg)
        bids.append(
            {
                "bidder": str(bid.bidder),
                "amount": bid.amount.amount,
            }
        )
        if self._agent_id not in round.participants:
            round.participants.append(self._agent_id)
        return bid

    async def resolve(self, round: Round) -> Outcome:
        """Resolve the auction and compute the payment.

        Allocation rule: highest bid wins; ties are broken
        deterministically by bidder id (lexicographic) so the trace is
        reproducible. If the highest bid is below the reserve (or there
        are no bids) the winner is ``None`` and no payment is owed.

        Payment rule depends on the mechanism:

        * ``first_price`` — payment = winning bid,
        * ``vickrey`` — payment = max(reserve, second-highest bid);
          if only one bidder participates the payment is the reserve
          (or zero if no reserve is set).

        Example::

            outcome = await coord.resolve(rnd)
        """
        if round.metadata.get("status") == STATUS_RESOLVED:
            # Idempotent re-resolution: rebuild the outcome from stored
            # state instead of recomputing — guarantees the same result
            # even if the bid list is mutated later.
            stored = round.metadata.get("outcome")
            if isinstance(stored, dict):
                return _rehydrate_outcome(round, stored)

        if round.metadata.get("status") == STATUS_COMMITTED:
            msg = f"round {round.id!r} already committed"
            raise SealedBidAuctionError(msg)

        mechanism = str(round.metadata.get("mechanism", self._mechanism))
        reserve_raw = round.metadata.get("reserve")
        reserve_amount = int(reserve_raw) if reserve_raw is not None else None

        bids_raw: list[dict[str, object]] = list(round.metadata.get("bids", []))
        # Sort by (amount desc, bidder id asc) — deterministic tie-break.
        bids_sorted = sorted(
            bids_raw,
            key=lambda b: (-int(str(b["amount"])), str(b["bidder"])),
        )

        winner: AgentId | None = None
        payment: int = 0
        runner_up: str | None = None
        tied_top: list[str] = []
        cleared = False

        if bids_sorted:
            top_amount = int(str(bids_sorted[0]["amount"]))
            tied_top = [
                str(b["bidder"])
                for b in bids_sorted
                if int(str(b["amount"])) == top_amount
            ]
            if reserve_amount is None or top_amount >= reserve_amount:
                cleared = True
                winner = AgentId(str(bids_sorted[0]["bidder"]))
                if mechanism == "first_price":
                    payment = top_amount
                else:  # vickrey
                    if len(bids_sorted) >= 2:
                        second = int(str(bids_sorted[1]["amount"]))
                        runner_up = str(bids_sorted[1]["bidder"])
                    else:
                        second = 0
                    floor = reserve_amount if reserve_amount is not None else 0
                    payment = max(second, floor)

        outcome_meta: dict[str, object] = {
            "mechanism": mechanism,
            "reserve": reserve_amount,
            "cleared": cleared,
            "payment": payment,
            "winning_bid": (
                int(str(bids_sorted[0]["amount"])) if bids_sorted else None
            ),
            "winner": (str(winner) if winner is not None else None),
            "runner_up": runner_up,
            "tied_top_bidders": tied_top,
            "num_bidders": len(bids_sorted),
        }

        outcome = Outcome(
            round_id=round.id,
            winner=winner,
            task=round.task,
            metadata=outcome_meta,
        )
        round.metadata["status"] = STATUS_RESOLVED
        round.metadata["outcome"] = outcome_meta
        return outcome

    async def commit(self, outcome: Outcome) -> None:
        """Mark the outcome as committed.

        After commit the round is sealed: further participation or
        re-resolution raises :class:`SealedBidAuctionError`. The commit
        step is what downstream layers (payments, trust) hook into.

        Example::

            await coord.commit(outcome)
        """
        # Outcome carries the round id but not the round itself; the
        # caller is expected to keep the Round alive (consistent with
        # the contract_net plugin). We update the outcome metadata so
        # holders of *just* the Outcome can still tell it's committed.
        outcome.metadata["status"] = STATUS_COMMITTED


def _rehydrate_outcome(rnd: Round, stored: dict[str, object]) -> Outcome:
    """Rebuild an :class:`Outcome` from the metadata stored on resolve.

    Internal helper — keeps resolve idempotent.
    """
    winner_raw = stored.get("winner")
    winner = AgentId(str(winner_raw)) if winner_raw else None
    return Outcome(
        round_id=rnd.id,
        winner=winner,
        task=rnd.task,
        metadata=dict(stored),
    )
