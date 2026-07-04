# SPDX-License-Identifier: Apache-2.0
# pyright: reportPrivateUsage=false
"""Unit tests for the agent_receipts trust plugin.

Covers receipt verification, counterparty corroboration, Tarjan-SCC collusion
severance (honest anchor vs isolated ring), the no-receipt fallback, and the
Trust-protocol surface. The make-or-break invariant -- that the honest
population is the *largest* SCC and only the ring is severed -- is asserted
directly against the severance primitive.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from nest_core.types import AgentId, Claim, Evidence
from nest_plugins_reference.trust.agent_receipts import (
    AgentReceiptsTrust,
    _corroboration_graph,
    _normalize,
    _sccs,
    _severed_dids,
    _verify_receipt,
    cosign_receipt,
    did_for_pubkey,
    is_corroborated,
    sign_receipt,
)


def _seed(name: str) -> bytes:
    return hashlib.sha256(name.encode()).digest()[:32]


def _did(name: str) -> str:
    sk = Ed25519PrivateKey.from_private_bytes(_seed(name))
    return did_for_pubkey(sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def _receipt(issuer: str, cp: str, *, rid: str, category: str = "purchase") -> dict[str, object]:
    r: dict[str, object] = {
        "receipt_id": rid,
        "issuer_did": _did(issuer),
        "action": {"category": category, "counterparty_did": _did(cp)},
    }
    return sign_receipt(r, issuer_seed=_seed(issuer))


def _corroborated(
    issuer: str, cp: str, *, rid: str, category: str = "purchase"
) -> dict[str, object]:
    return cosign_receipt(
        _receipt(issuer, cp, rid=rid, category=category), counterparty_seed=_seed(cp)
    )


class TestReceiptVerification:
    def test_valid_issuer_signature_verifies(self) -> None:
        assert _verify_receipt(_receipt("a", "b", rid="r0")) is True

    def test_tampered_action_fails_verification(self) -> None:
        r = _receipt("a", "b", rid="r0")
        r["action"] = {"category": "payment_sent", "counterparty_did": _did("b")}  # post-sign edit
        assert _verify_receipt(r) is False

    def test_missing_signature_fails_without_crashing(self) -> None:
        r = {"receipt_id": "r0", "issuer_did": _did("a"), "action": {"category": "purchase"}}
        assert _verify_receipt(r) is False

    def test_garbage_signature_fails_without_crashing(self) -> None:
        r = _receipt("a", "b", rid="r0")
        r["signature"] = "not-hex"
        assert _verify_receipt(r) is False


class TestCorroboration:
    def test_counterparty_cosignature_is_corroborated(self) -> None:
        assert is_corroborated(_corroborated("a", "b", rid="r0")) is True

    def test_uncosigned_receipt_not_corroborated(self) -> None:
        assert is_corroborated(_receipt("a", "b", rid="r0")) is False

    def test_self_corroboration_rejected(self) -> None:
        # counterparty == issuer: not a distinct corroborator.
        assert is_corroborated(_corroborated("a", "a", rid="r0")) is False

    def test_wrong_witness_signature_not_corroborated(self) -> None:
        r = _receipt("a", "b", rid="r0")
        r.setdefault("evidence", {})["witness_signatures"] = [  # type: ignore[index]
            {"witness_did": _did("b"), "signature": "00" * 64}
        ]
        assert is_corroborated(r) is False


class TestSeverance:
    def _honest_and_ring(self) -> list[dict[str, object]]:
        honest = [f"h{i}" for i in range(5)]
        ring = [f"r{i}" for i in range(4)]
        receipts: list[dict[str, object]] = []
        # honest directed cycle + chord -> single SCC of size 5
        for i in range(5):
            for k in (1, 2):
                receipts.append(_corroborated(honest[i], honest[(i + k) % 5], rid=f"h{i}-{k}"))
        # isolated dense ring (all-pairs both directions)
        for i in range(4):
            for j in range(4):
                if i != j:
                    receipts.append(_corroborated(ring[i], ring[j], rid=f"r{i}-{j}"))
        return receipts

    def test_anchor_is_largest_honest_scc(self) -> None:
        """The honest population must be the anchor (largest SCC), strictly > ring."""
        graph = _corroboration_graph(self._honest_and_ring())
        comps = _sccs(graph)
        anchor = set(comps[0])
        assert anchor == {_did(f"h{i}") for i in range(5)}
        assert len(anchor) > 4  # strictly larger than the 4-agent ring

    def test_isolated_ring_is_severed(self) -> None:
        severed = _severed_dids(_corroboration_graph(self._honest_and_ring()))
        assert severed == {_did(f"r{i}") for i in range(4)}

    def test_ring_with_edge_to_anchor_not_severed(self) -> None:
        """A ring that actually transacts with an honest agent is not isolated."""
        receipts = self._honest_and_ring()
        # add a real corroborated edge ring->honest, bridging the ring to the anchor
        receipts.append(_corroborated("r0", "h0", rid="bridge"))
        severed = _severed_dids(_corroboration_graph(receipts))
        assert severed == set()

    def test_empty_graph_severs_nothing(self) -> None:
        assert _severed_dids({}) == set()


class TestScore:
    @pytest.mark.asyncio
    async def test_honest_scored_ring_severed(self) -> None:
        trust = AgentReceiptsTrust()
        honest = [f"honest-{i}" for i in range(5)]
        ring = [f"ring-{i}" for i in range(4)]
        for i in range(5):
            for k in (1, 2):
                r = _corroborated(honest[i], honest[(i + k) % 5], rid=f"h{i}-{k}")
                await trust.report(
                    AgentId(honest[i]),
                    Evidence(
                        reporter=AgentId(honest[i]),
                        subject=AgentId(honest[i]),
                        kind="positive",
                        detail=json.dumps(r),
                    ),
                )
        for i in range(4):
            for j in range(4):
                if i != j:
                    r = _corroborated(ring[i], ring[j], rid=f"r{i}-{j}")
                    await trust.report(
                        AgentId(ring[i]),
                        Evidence(
                            reporter=AgentId(ring[i]),
                            subject=AgentId(ring[i]),
                            kind="positive",
                            detail=json.dumps(r),
                        ),
                    )
        honest_score = await trust.score(AgentId("honest-0"))
        ring_score = await trust.score(AgentId("ring-0"))
        assert honest_score.score > 0.0
        assert honest_score.confidence == 1.0
        # severed: zero score AND zero confidence, but sample_count records the claim
        assert ring_score.score == 0.0
        assert ring_score.confidence == 0.0
        assert ring_score.sample_count > 0

    @pytest.mark.asyncio
    async def test_no_receipts_returns_neutral_prior(self) -> None:
        rep = await AgentReceiptsTrust().score(AgentId("nobody"))
        assert rep.score == 0.5
        assert rep.confidence == 0.0
        assert rep.sample_count == 0

    @pytest.mark.asyncio
    async def test_plain_string_detail_falls_back(self) -> None:
        """Stock-scenario plain-string detail uses the score-average heuristic."""
        trust = AgentReceiptsTrust()
        await trust.report(
            AgentId("a"),
            Evidence(reporter=AgentId("r"), subject=AgentId("a"), kind="positive", detail="ok"),
        )
        rep = await trust.score(AgentId("a"))
        assert rep.score == 1.0
        assert rep.sample_count == 1

    @pytest.mark.asyncio
    async def test_invalid_receipt_dict_falls_back_not_crashes(self) -> None:
        trust = AgentReceiptsTrust()
        bad = json.dumps({"issuer_did": _did("a"), "signature": "deadbeef", "action": {}})
        await trust.report(
            AgentId("a"),
            Evidence(reporter=AgentId("r"), subject=AgentId("a"), kind="negative", detail=bad),
        )
        rep = await trust.score(AgentId("a"))
        # fell back to heuristic (negative -> 0.0), did not enter the ledger
        assert rep.score == 0.0
        assert rep.sample_count == 1


class TestProtocolSurface:
    @pytest.mark.asyncio
    async def test_attest_produces_signed_attestation(self) -> None:
        trust = AgentReceiptsTrust()
        claim = Claim(subject=AgentId("a"), predicate="completed", value="task-1")
        att = await trust.attest(AgentId("a"), claim)
        assert att.claim == claim
        assert att.signature.algorithm == "ed25519"
        assert len(att.signature.value) == 64

    @pytest.mark.asyncio
    async def test_stake_is_noop_parity(self) -> None:
        trust = AgentReceiptsTrust()
        await trust.stake(AgentId("a"), 100)  # must not raise

    def test_normalize_bounds(self) -> None:
        assert _normalize(0.0) == 0.0
        assert 0.0 < _normalize(5.0) < 1.0
        assert _normalize(5.0) == pytest.approx(0.39346934, abs=1e-6)
