# SPDX-License-Identifier: Apache-2.0
"""Mechanism-design property checks for :mod:`sealed_bid`.

These helpers are pure functions over a :class:`Round` / :class:`Outcome`
(no I/O) and return ``ValidationResult`` records compatible with the
``nest_core.validators`` style. They make it trivial for downstream
tests and validators to assert mechanism-design invariants such as:

* **Allocative efficiency** — the agent with the highest bid wins
  whenever the reserve is met.
* **Individual rationality (winner)** — winner pays at most their bid.
* **No-deficit (seller IR)** — payment ≥ reserve when the auction
  clears.
* **Vickrey payment correctness** — for a second-price mechanism the
  payment equals the second-highest bid (or the reserve if higher /
  only one bidder).
* **Single-winner** — at most one winning agent per round.

The properties are checked over the resolved :class:`Outcome` and the
list of bids stored in ``round.metadata['bids']``. Designed to be
reused both inside unit tests and inside trace-level validators.

Example::

    rnd = await coord.propose(task)
    await b1.participate(rnd, value=Money(amount=80))
    await b2.participate(rnd, value=Money(amount=100))
    outcome = await coord.resolve(rnd)

    results = check_round(rnd, outcome)
    assert all(r.passed for r in results)
"""

from __future__ import annotations

from dataclasses import dataclass

from nest_core.types import Outcome, Round


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of a single property check.

    Example::

        r = ValidationResult(name="single_winner", passed=True, detail="ok")
    """

    name: str
    passed: bool
    detail: str = ""


def _bids_of(rnd: Round) -> list[tuple[str, int]]:
    raw = rnd.metadata.get("bids", [])
    out: list[tuple[str, int]] = []
    if isinstance(raw, list):
        for b in raw:
            if isinstance(b, dict):
                bidder = str(b.get("bidder", ""))
                try:
                    amount = int(str(b.get("amount", 0)))
                except (TypeError, ValueError):
                    continue
                out.append((bidder, amount))
    return out


def check_allocative_efficiency(rnd: Round, outcome: Outcome) -> ValidationResult:
    """The winner has the highest bid (ties broken deterministically).

    Vacuously passes when no bids were placed.

    Example::

        r = check_allocative_efficiency(rnd, outcome)
    """
    bids = _bids_of(rnd)
    if not bids:
        return ValidationResult(
            "allocative_efficiency",
            passed=True,
            detail="no bids",
        )
    top_amount = max(amount for _, amount in bids)
    reserve = outcome.metadata.get("reserve")

    if outcome.winner is None:
        if reserve is not None and top_amount < int(str(reserve)):
            return ValidationResult(
                "allocative_efficiency",
                passed=True,
                detail=f"reserve {reserve} > top bid {top_amount}",
            )
        return ValidationResult(
            "allocative_efficiency",
            passed=False,
            detail=(
                f"no winner declared but top bid {top_amount} "
                f"clears reserve {reserve}"
            ),
        )

    winner = str(outcome.winner)
    winner_bid = next((amt for b, amt in bids if b == winner), None)
    if winner_bid is None:
        return ValidationResult(
            "allocative_efficiency",
            passed=False,
            detail=f"winner {winner!r} did not bid",
        )
    if winner_bid != top_amount:
        return ValidationResult(
            "allocative_efficiency",
            passed=False,
            detail=(
                f"winner {winner!r} bid {winner_bid}, "
                f"highest bid was {top_amount}"
            ),
        )
    return ValidationResult(
        "allocative_efficiency",
        passed=True,
        detail=f"winner={winner} bid={winner_bid}",
    )


def check_winner_ir(rnd: Round, outcome: Outcome) -> ValidationResult:
    """Winner pays no more than they bid (winner individual rationality).

    Example::

        r = check_winner_ir(rnd, outcome)
    """
    if outcome.winner is None:
        return ValidationResult("winner_ir", passed=True, detail="no winner")
    bids = _bids_of(rnd)
    winner = str(outcome.winner)
    winner_bid = next((amt for b, amt in bids if b == winner), None)
    payment_raw = outcome.metadata.get("payment", 0)
    try:
        payment = int(str(payment_raw))
    except (TypeError, ValueError):
        return ValidationResult(
            "winner_ir",
            passed=False,
            detail=f"payment {payment_raw!r} is not an integer",
        )
    if winner_bid is None:
        return ValidationResult(
            "winner_ir",
            passed=False,
            detail=f"winner {winner!r} did not bid",
        )
    if payment > winner_bid:
        return ValidationResult(
            "winner_ir",
            passed=False,
            detail=f"payment {payment} > winner bid {winner_bid}",
        )
    return ValidationResult(
        "winner_ir",
        passed=True,
        detail=f"payment={payment} <= bid={winner_bid}",
    )


def check_seller_reserve(rnd: Round, outcome: Outcome) -> ValidationResult:
    """Payment respects the reserve price.

    If the auction clears the payment must be at least the reserve; if
    it does not clear the payment must be zero.

    Example::

        r = check_seller_reserve(rnd, outcome)
    """
    reserve_raw = outcome.metadata.get("reserve")
    payment_raw = outcome.metadata.get("payment", 0)
    try:
        payment = int(str(payment_raw))
    except (TypeError, ValueError):
        return ValidationResult(
            "seller_reserve",
            passed=False,
            detail=f"payment {payment_raw!r} is not an integer",
        )
    if outcome.winner is None:
        if payment != 0:
            return ValidationResult(
                "seller_reserve",
                passed=False,
                detail=f"no winner but payment is {payment}",
            )
        return ValidationResult(
            "seller_reserve", passed=True, detail="no winner, no payment"
        )
    if reserve_raw is None:
        return ValidationResult(
            "seller_reserve", passed=True, detail="no reserve set"
        )
    reserve = int(str(reserve_raw))
    if payment < reserve:
        return ValidationResult(
            "seller_reserve",
            passed=False,
            detail=f"payment {payment} < reserve {reserve}",
        )
    return ValidationResult(
        "seller_reserve",
        passed=True,
        detail=f"payment={payment} >= reserve={reserve}",
    )


def check_vickrey_payment(rnd: Round, outcome: Outcome) -> ValidationResult:
    """Under Vickrey, payment equals max(reserve, second-highest bid).

    Vacuously passes for non-Vickrey mechanisms.

    Example::

        r = check_vickrey_payment(rnd, outcome)
    """
    mechanism = str(outcome.metadata.get("mechanism", ""))
    if mechanism != "vickrey":
        return ValidationResult(
            "vickrey_payment",
            passed=True,
            detail=f"mechanism={mechanism!r}, not vickrey",
        )
    if outcome.winner is None:
        return ValidationResult(
            "vickrey_payment", passed=True, detail="no winner"
        )

    bids = sorted(
        (amt for _, amt in _bids_of(rnd)), reverse=True
    )
    if not bids:
        return ValidationResult(
            "vickrey_payment",
            passed=False,
            detail="winner declared with no bids",
        )
    second = bids[1] if len(bids) >= 2 else 0
    reserve_raw = outcome.metadata.get("reserve")
    floor = int(str(reserve_raw)) if reserve_raw is not None else 0
    expected = max(second, floor)
    payment_raw = outcome.metadata.get("payment", 0)
    try:
        payment = int(str(payment_raw))
    except (TypeError, ValueError):
        return ValidationResult(
            "vickrey_payment",
            passed=False,
            detail=f"payment {payment_raw!r} is not an integer",
        )
    if payment != expected:
        return ValidationResult(
            "vickrey_payment",
            passed=False,
            detail=(
                f"payment={payment} but expected max(reserve={floor}, "
                f"second={second})={expected}"
            ),
        )
    return ValidationResult(
        "vickrey_payment",
        passed=True,
        detail=f"payment={payment} = max(reserve={floor}, second={second})",
    )


def check_first_price_payment(rnd: Round, outcome: Outcome) -> ValidationResult:
    """Under first-price, payment equals the winning bid.

    Vacuously passes for non-first-price mechanisms.

    Example::

        r = check_first_price_payment(rnd, outcome)
    """
    mechanism = str(outcome.metadata.get("mechanism", ""))
    if mechanism != "first_price":
        return ValidationResult(
            "first_price_payment",
            passed=True,
            detail=f"mechanism={mechanism!r}, not first_price",
        )
    if outcome.winner is None:
        return ValidationResult(
            "first_price_payment", passed=True, detail="no winner"
        )
    winning_bid_raw = outcome.metadata.get("winning_bid")
    payment_raw = outcome.metadata.get("payment", 0)
    try:
        winning_bid = int(str(winning_bid_raw))
        payment = int(str(payment_raw))
    except (TypeError, ValueError):
        return ValidationResult(
            "first_price_payment",
            passed=False,
            detail=(
                f"non-integer payment/winning_bid: "
                f"payment={payment_raw!r}, winning_bid={winning_bid_raw!r}"
            ),
        )
    if payment != winning_bid:
        return ValidationResult(
            "first_price_payment",
            passed=False,
            detail=f"payment={payment} != winning_bid={winning_bid}",
        )
    return ValidationResult(
        "first_price_payment",
        passed=True,
        detail=f"payment={payment} == winning_bid={winning_bid}",
    )


def check_single_winner(rnd: Round, outcome: Outcome) -> ValidationResult:
    """At most one winning agent per round.

    Single-winner is structurally enforced by :class:`Outcome` having a
    single ``winner`` field, so this check exists primarily as a guard
    against tied top bidders being silently treated as joint winners.

    Example::

        r = check_single_winner(rnd, outcome)
    """
    tied = outcome.metadata.get("tied_top_bidders", [])
    if outcome.winner is None:
        return ValidationResult(
            "single_winner", passed=True, detail="no winner"
        )
    if isinstance(tied, list) and len(tied) > 1:
        # A tied top is allowed *if* the chosen winner is the
        # deterministic lexicographic minimum — that is the documented
        # tie-break. Otherwise flag it.
        chosen = str(outcome.winner)
        expected = min(str(t) for t in tied)
        if chosen != expected:
            return ValidationResult(
                "single_winner",
                passed=False,
                detail=(
                    f"tied top {tied!r} but winner {chosen!r} "
                    f"!= deterministic min {expected!r}"
                ),
            )
    return ValidationResult(
        "single_winner",
        passed=True,
        detail=f"winner={outcome.winner}",
    )


def check_round(rnd: Round, outcome: Outcome) -> list[ValidationResult]:
    """Run all sealed-bid mechanism properties on a round/outcome.

    Example::

        for r in check_round(rnd, outcome):
            assert r.passed, r.detail
    """
    return [
        check_allocative_efficiency(rnd, outcome),
        check_winner_ir(rnd, outcome),
        check_seller_reserve(rnd, outcome),
        check_vickrey_payment(rnd, outcome),
        check_first_price_payment(rnd, outcome),
        check_single_winner(rnd, outcome),
    ]
