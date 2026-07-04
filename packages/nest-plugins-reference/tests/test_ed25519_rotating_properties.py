# SPDX-License-Identifier: Apache-2.0
"""Hypothesis property-based tests for the ``ed25519_rotating`` identity plugin.

Each invariant is checked over generated payloads, seeds, tick values, and
rotation counts so the as-of verification rules hold for *all* inputs, not just
the hand-picked cases in ``test_ed25519_rotating.py``:

1. Sign/verify round-trip inside the signing key's validity window.
2. As-of correctness: accept iff the observed tick is in ``[issued_at, rotated_out)``.
3. Post-rotation forgery is always rejected at any tick ``>= rotated_out``.
4. Backdating (claimed ``signed_at`` before the new key's ``issued_at``) is rejected.
5. ``key_id`` binding: a signature carries its producing key and never verifies
   as-of a different key's window.
6. Determinism: same seed -> same ``key_id`` and identical signature bytes.
7. Continuity: after ``rotate_key`` the rotation record verifies under the prior key.

The plugin clock advances forward-only (``set_clock`` ignores non-increasing
ticks), so every test draws *bounds* and applies ticks in strictly ascending
order. Ticks are integer-valued (cast to ``float``) to keep the half-open
boundary equality (``tick == rotated_out``) exact and CI non-flaky.

Example::

    pytest packages/nest-plugins-reference/tests/test_ed25519_rotating_properties.py
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from nest_core.types import AgentId, Signature
from nest_plugins_reference.identity.ed25519_rotating import (
    ALGORITHM,
    Ed25519RotatingIdentity,
)

# Bounded strategies: small payloads/seeds keep crypto cheap; integer ticks
# (cast to float) keep half-open-window boundary equality exact.
_payloads = st.binary(min_size=0, max_size=256)
_seeds = st.binary(min_size=0, max_size=64)
_ticks = st.integers(min_value=0, max_value=10_000).map(float)


def _ident(name: str = "a1", seed: bytes = b"seed") -> Ed25519RotatingIdentity:
    return Ed25519RotatingIdentity(AgentId(name), seed=seed)


# ---------------------------------------------------------------------------
# 1. Sign/verify round-trip inside the signing key's window
# ---------------------------------------------------------------------------


class TestSignVerifyRoundTrip:
    @settings(max_examples=50, deadline=None)
    @given(payload=_payloads, seed=_seeds, sign_tick=_ticks, delta=_ticks)
    def test_signature_verifies_within_window(
        self, payload: bytes, seed: bytes, sign_tick: float, delta: float
    ) -> None:
        """A signature by the current (never-rotated) key verifies as-of any tick
        in its window. With no rotation the window is ``[0, +inf)``, so any
        observed tick >= the issue tick is inside it."""
        ident = _ident(seed=seed)
        ident.set_clock(sign_tick)
        sig = ident.sign(payload)
        observed = sign_tick + delta  # still inside the open-ended window
        assert ident.verify(payload, sig, AgentId("a1"), as_of=observed)


# ---------------------------------------------------------------------------
# 2. As-of correctness: accept iff observed tick in [issued_at, rotated_out)
# ---------------------------------------------------------------------------


class TestAsOfCorrectness:
    @settings(max_examples=50, deadline=None)
    @given(
        payload=_payloads,
        seed=_seeds,
        ticks=st.lists(_ticks, min_size=2, max_size=4),
        obs=_ticks,
    )
    def test_old_key_accepts_iff_observed_in_its_window(
        self, payload: bytes, seed: bytes, ticks: list[float], obs: float
    ) -> None:
        """Sign with key #0, rotate once, then for an arbitrary observed tick the
        old signature verifies iff that tick lies in the old key's
        ``[issued_at=0, rotated_out=rotate_at)`` half-open window.

        The oracle is the independent numeric window condition, NOT
        ``record.is_valid_at`` (which ``verify`` itself calls — asserting against
        it would be tautological)."""
        sorted_ticks = sorted(ticks)
        sign_at = sorted_ticks[0]
        rotate_at = sorted_ticks[-1]
        if rotate_at <= sign_at:  # need a non-empty window to sign inside
            return

        ident = _ident(seed=seed)
        ident.set_clock(sign_at)
        old_sig = ident.sign(payload)
        ident.set_clock(rotate_at)
        ident.rotate_key(b"rotated-seed")

        # Independent oracle: old key window is [0.0, rotate_at).
        in_old_window = 0.0 <= obs < rotate_at
        assert ident.verify(payload, old_sig, AgentId("a1"), as_of=obs) == in_old_window

    @settings(max_examples=50, deadline=None)
    @given(
        payload=_payloads,
        seed=_seeds,
        rotations=st.integers(min_value=1, max_value=5),
        gaps=st.lists(st.integers(min_value=1, max_value=500), min_size=5, max_size=5),
        obs=_ticks,
    )
    def test_as_of_selects_correct_key_across_full_history(
        self,
        payload: bytes,
        seed: bytes,
        rotations: int,
        gaps: list[int],
        obs: float,
    ) -> None:
        """Generalises invariants 2 + 5 over a *multi-rotation* key history.

        Build ``rotations`` keys at strictly ascending rotation ticks, signing
        one payload under each key while it is current. The resulting windows are
        ``[0, t1), [t1, t2), ..., [tN, +inf)``. For an arbitrary observed tick,
        each signature must verify **iff** that tick lies in its own key's
        ``[issued_at, rotated_out)`` window — proving as-of *selection* picks the
        right key out of a real history, not just a single rotation. Oracle is
        the independent numeric window bound."""
        ident = _ident(seed=seed)

        # Rotation ticks strictly ascending: cumulative sum of positive gaps.
        rotate_ticks: list[float] = []
        t = 0.0
        for i in range(rotations):
            t += float(gaps[i])
            rotate_ticks.append(t)

        # Key windows: key0=[0, r0), key1=[r0, r1), ..., keyN=[r_{N-1}, inf).
        boundaries = [0.0, *rotate_ticks, float("inf")]
        signed: list[tuple[Signature, float, float]] = []  # (sig, issued, rotated_out)
        for i in range(rotations + 1):
            issued = boundaries[i]
            rotated_out = boundaries[i + 1]
            # Sign while this key is current: clock at its issue tick (>= prior,
            # so set_clock takes; first key issued at 0 == initial clock).
            ident.set_clock(issued)
            signed.append((ident.sign(payload), issued, rotated_out))
            if i < rotations:  # rotate into the next key at its boundary tick
                ident.set_clock(rotate_ticks[i])
                ident.rotate_key(b"seed-%d" % i)

        for sig, issued, rotated_out in signed:
            expected = issued <= obs < rotated_out
            assert ident.verify(payload, sig, AgentId("a1"), as_of=obs) == expected


# ---------------------------------------------------------------------------
# 3. Post-rotation forgery always fails
# ---------------------------------------------------------------------------


class TestPostRotationForgery:
    @settings(max_examples=50, deadline=None)
    @given(payload=_payloads, seed=_seeds, rotate_at=_ticks, delta=_ticks)
    def test_forged_old_key_signature_rejected_after_rotation(
        self, payload: bytes, seed: bytes, rotate_at: float, delta: float
    ) -> None:
        """A real Ed25519 signature forged with the rotated-out key, presented at
        any observed tick >= its ``rotated_out``, is rejected (the window is
        closed). ``tick == rotated_out`` already fails since the window is
        half-open."""
        ident = _ident(seed=seed)
        old_key = ident.current_key_id
        ident.set_clock(rotate_at)
        ident.rotate_key(b"rotated-seed")
        # Forge AT/after rotation with the stale key (clock >= rotate_at).
        forged = ident.sign_with(payload, old_key)
        observed = rotate_at + delta  # >= rotated_out
        assert not ident.verify(payload, forged, AgentId("a1"), as_of=observed)


# ---------------------------------------------------------------------------
# 4. Backdating always fails
# ---------------------------------------------------------------------------


class TestBackdating:
    @settings(max_examples=50, deadline=None)
    @given(payload=_payloads, seed=_seeds, rotate_at=_ticks, sign_delta=_ticks, back_delta=_ticks)
    def test_new_key_signature_backdated_before_issue_rejected(
        self,
        payload: bytes,
        seed: bytes,
        rotate_at: float,
        sign_delta: float,
        back_delta: float,
    ) -> None:
        """A signature made by the *new* key, presented as-of a tick strictly
        before the new key's ``issued_at`` (== ``rotate_at``), is rejected: the
        new key's window does not yet contain it. The verifier anchors on the
        externally observed tick, never the attacker-controlled claim."""
        ident = _ident(seed=seed)
        ident.set_clock(rotate_at)
        ident.rotate_key(b"rotated-seed")
        ident.set_clock(rotate_at + sign_delta)  # ascending; sign with new key
        new_sig = ident.sign(payload)

        # Backdate strictly before the new key's issued_at. If rotate_at == 0
        # there is no earlier tick, so skip (nothing to backdate to).
        if rotate_at <= 0.0:
            return
        backdated = max(0.0, rotate_at - 1.0 - back_delta)
        assert backdated < rotate_at
        # Forge the advisory claim too: the attacker stamps signed_at to the old
        # tick. The verifier must ignore it and anchor on the observed as_of.
        new_sig.signed_at = backdated
        assert not ident.verify(payload, new_sig, AgentId("a1"), as_of=backdated)


# ---------------------------------------------------------------------------
# 5. key_id binding
# ---------------------------------------------------------------------------


class TestKeyIdBinding:
    @settings(max_examples=50, deadline=None)
    @given(payload=_payloads, seed=_seeds)
    def test_signature_key_id_matches_producing_key(self, payload: bytes, seed: bytes) -> None:
        """Every signature's ``key_id`` equals the key that produced it."""
        ident = _ident(seed=seed)
        expected = str(ident.current_key_id)
        sig = ident.sign(payload)
        assert sig.key_id == expected
        assert sig.algorithm == ALGORITHM

    @settings(max_examples=50, deadline=None)
    @given(payload=_payloads, seed=_seeds, sign_at=_ticks, gap=_ticks)
    def test_signature_never_verifies_as_of_other_keys_window(
        self, payload: bytes, seed: bytes, sign_at: float, gap: float
    ) -> None:
        """A signature bound to the old ``key_id`` is checked against the OLD
        key's closed window, never against whichever key happens to be valid at
        the observed tick. So an old signature presented inside the *new* key's
        window is rejected even though some key is valid there."""
        rotate_at = sign_at + 1.0 + gap  # strictly after sign_at, ascending
        ident = _ident(seed=seed)
        ident.set_clock(sign_at)
        old_sig = ident.sign(payload)
        old_key = old_sig.key_id
        ident.set_clock(rotate_at)
        ident.rotate_key(b"rotated-seed")
        new_key = str(ident.current_key_id)

        assert old_key is not None and old_key != new_key
        # Observed inside the NEW key's window (>= rotate_at): old key's window
        # is closed there, so the old-key-bound signature must be rejected.
        assert not ident.verify(payload, old_sig, AgentId("a1"), as_of=rotate_at)


# ---------------------------------------------------------------------------
# 6. Determinism (Tier-1 replay)
# ---------------------------------------------------------------------------


class TestDeterminism:
    @settings(max_examples=50, deadline=None)
    @given(payload=_payloads, seed=_seeds)
    def test_same_seed_same_key_id_and_signature_bytes(self, payload: bytes, seed: bytes) -> None:
        """Two identities built from the same seed produce the same ``key_id`` and
        byte-identical signatures over the same payload (Ed25519 is deterministic
        and seeds derive deterministically)."""
        a = _ident(seed=seed)
        b = _ident(seed=seed)
        assert a.current_key_id == b.current_key_id
        sig_a = a.sign(payload)
        sig_b = b.sign(payload)
        assert sig_a.value == sig_b.value
        assert sig_a.key_id == sig_b.key_id

    @settings(max_examples=50, deadline=None)
    @given(seed=_seeds, rotate_at=_ticks, new_seed=_seeds)
    def test_same_seed_same_rotation_continuity(
        self, seed: bytes, rotate_at: float, new_seed: bytes
    ) -> None:
        """Same seed + same rotation clock + same new seed -> same successor
        ``key_id`` and identical continuity signature bytes."""
        a = _ident(seed=seed)
        b = _ident(seed=seed)
        a.set_clock(rotate_at)
        b.set_clock(rotate_at)
        rec_a = a.rotate_key(new_seed)
        rec_b = b.rotate_key(new_seed)
        assert rec_a.new_key_id == rec_b.new_key_id
        assert rec_a.continuity_signature == rec_b.continuity_signature


# ---------------------------------------------------------------------------
# 7. Continuity: rotation record verifies under the prior key
# ---------------------------------------------------------------------------


class TestContinuity:
    @settings(max_examples=50, deadline=None)
    @given(seed=_seeds, rotate_at=_ticks, new_seed=_seeds)
    def test_rotation_record_verifies_under_prior_key(
        self, seed: bytes, rotate_at: float, new_seed: bytes
    ) -> None:
        """``rotate_key`` returns a record whose continuity signature is by the
        prior key over the new key's published bytes; ``verify_continuity``
        accepts it (the just-rotated key is still the chain tip from the
        agent's own view)."""
        ident = _ident(seed=seed)
        old_key = ident.current_key_id
        ident.set_clock(rotate_at)
        rec = ident.rotate_key(new_seed)
        assert rec.old_key_id == old_key
        assert ident.verify_continuity(AgentId("a1"), rec)

    @settings(max_examples=50, deadline=None)
    @given(seed=_seeds, rotate_at=_ticks, new_seed=_seeds)
    def test_tampered_continuity_signature_rejected(
        self, seed: bytes, rotate_at: float, new_seed: bytes
    ) -> None:
        """Flipping the continuity signature to garbage breaks verification for
        any seed/tick (crypto check fails)."""
        ident = _ident(seed=seed)
        ident.set_clock(rotate_at)
        rec = ident.rotate_key(new_seed)
        rec.continuity_signature = b"\x00" * 64
        assert not ident.verify_continuity(AgentId("a1"), rec)


def test_signature_model_optional_fields_default_none() -> None:
    """Sanity anchor: a plain did_key-style Signature has no key_id/signed_at."""
    sig = Signature(signer=AgentId("a1"), value=b"x", algorithm="sim-rsa-sha256")
    assert sig.key_id is None
    assert sig.signed_at is None
