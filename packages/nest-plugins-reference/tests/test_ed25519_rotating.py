# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the ``ed25519_rotating`` identity plugin.

Covers real Ed25519 sign/verify, key rotation with as-of historical
verification, the two adversarial attacks the plugin defeats (post-rotation
forgery and backdating), continuity signatures, ``did_key`` caller
compatibility on the shared ``Signature`` model, and determinism.

Example::

    pytest packages/nest-plugins-reference/tests/test_ed25519_rotating.py
"""

from __future__ import annotations

import pytest
from nest_core.types import AgentId, Signature
from nest_plugins_reference.identity.ed25519_rotating import (
    ALGORITHM,
    Ed25519RotatingIdentity,
    KeyId,
)


def _ident(name: str = "a1", seed: bytes = b"seed") -> Ed25519RotatingIdentity:
    return Ed25519RotatingIdentity(AgentId(name), seed=seed)


class TestEd25519SignVerify:
    def test_sign_verify_roundtrip(self) -> None:
        ident = _ident()
        sig = ident.sign(b"hello")
        assert sig.algorithm == ALGORITHM
        assert sig.key_id is not None
        assert ident.verify(b"hello", sig, AgentId("a1"))

    def test_verify_rejects_wrong_payload(self) -> None:
        ident = _ident()
        sig = ident.sign(b"hello")
        assert not ident.verify(b"tampered", sig, AgentId("a1"))

    def test_verify_rejects_wrong_signer(self) -> None:
        ident = _ident()
        sig = ident.sign(b"hello")
        assert not ident.verify(b"hello", sig, AgentId("someone-else"))

    def test_public_key_is_raw_32_bytes(self) -> None:
        assert len(_ident().public_key) == 32

    def test_private_key_never_serialised(self) -> None:
        # resolve()'s exported history must carry public material only.
        ident = _ident()
        import asyncio

        record = asyncio.run(ident.resolve(AgentId("a1")))
        for key in record.metadata["keys"]:
            assert set(key) == {"key_id", "public_key", "issued_at", "rotated_out"}
            assert "private" not in str(key).lower()


class TestRotationAsOf:
    def test_rotation_changes_key(self) -> None:
        ident = _ident()
        before = ident.current_key_id
        ident.set_clock(5.0)
        rec = ident.rotate_key(b"new")
        after = ident.current_key_id
        assert before != after
        assert rec.old_key_id == before
        assert rec.new_key_id == after

    def test_old_signature_verifies_as_of_old_window(self) -> None:
        ident = _ident()
        ident.set_clock(1.0)
        old_sig = ident.sign(b"made-at-1")
        ident.set_clock(5.0)
        ident.rotate_key(b"new")
        # The old signature still verifies when anchored inside the old window.
        assert ident.verify(b"made-at-1", old_sig, AgentId("a1"), as_of=1.0)

    def test_old_signature_fails_as_of_after_rotation(self) -> None:
        ident = _ident()
        ident.set_clock(1.0)
        old_sig = ident.sign(b"made-at-1")
        ident.set_clock(5.0)
        ident.rotate_key(b"new")
        # Anchored after rotation, the old key's window no longer contains it.
        assert not ident.verify(b"made-at-1", old_sig, AgentId("a1"), as_of=5.0)

    def test_new_signature_verifies_as_of_current(self) -> None:
        ident = _ident()
        ident.set_clock(5.0)
        ident.rotate_key(b"new")
        ident.set_clock(6.0)
        new_sig = ident.sign(b"made-at-6")
        assert ident.verify(b"made-at-6", new_sig, AgentId("a1"), as_of=6.0)


class TestPostRotationForgery:
    def test_forged_old_key_signature_rejected(self) -> None:
        """An attacker forging with the stale key AFTER rotation must fail.

        The forgery is a *real* Ed25519 signature by the old key, so it is not a
        crypto mismatch — it is rejected because, anchored at the current
        (post-rotation) tick, the old key's window is closed.
        """
        ident = _ident()
        old_key = ident.current_key_id
        ident.set_clock(5.0)
        ident.rotate_key(b"new")
        ident.set_clock(9.0)
        forged = ident.sign_with(b"forged-after-rotation", old_key)
        # Forgery observed/verified at the current tick (9.0, past rotated_out=5).
        assert not ident.verify(b"forged-after-rotation", forged, AgentId("a1"), as_of=9.0)

    def test_forged_signature_is_real_crypto_not_tamper(self) -> None:
        # Prove the rejection is about the window, not a bad signature: the same
        # forged signature DOES verify if anchored inside the old window. That is
        # the honest threat model — a compromised key can sign in its own window.
        ident = _ident()
        old_key = ident.current_key_id
        ident.set_clock(1.0)
        forged = ident.sign_with(b"x", old_key)
        ident.set_clock(5.0)
        ident.rotate_key(b"new")
        assert ident.verify(b"x", forged, AgentId("a1"), as_of=1.0)
        assert not ident.verify(b"x", forged, AgentId("a1"), as_of=5.0)


class TestBackdating:
    def test_backdated_new_key_signature_rejected(self) -> None:
        """A new-key signature claimed to belong in the old window must fail.

        Anchored at an old tick (before the new key was issued), the new key's
        window does not contain it.
        """
        ident = _ident()
        ident.set_clock(5.0)
        ident.rotate_key(b"new")
        ident.set_clock(6.0)
        new_sig = ident.sign(b"really-made-at-6")
        # Attacker backdates: verify as-of an old tick (1.0) inside the old window.
        assert not ident.verify(b"really-made-at-6", new_sig, AgentId("a1"), as_of=1.0)

    def test_backdated_signature_valid_at_true_tick(self) -> None:
        # The same signature is valid at its true (current) tick — the backdate
        # is the only thing rejected.
        ident = _ident()
        ident.set_clock(5.0)
        ident.rotate_key(b"new")
        ident.set_clock(6.0)
        new_sig = ident.sign(b"really-made-at-6")
        assert ident.verify(b"really-made-at-6", new_sig, AgentId("a1"), as_of=6.0)


class TestContinuity:
    def test_continuity_signature_by_old_key(self) -> None:
        ident = _ident()
        ident.set_clock(5.0)
        rec = ident.rotate_key(b"new")
        # The continuity signature is by the OLD key over the new key's record.
        assert ident.verify_continuity(AgentId("a1"), rec)

    def test_apply_rotation_on_verified_peer_record(self) -> None:
        # A peer adopts another agent's rotation only if continuity checks out.
        signer = _ident("signer")
        old_pub = signer.public_key  # capture before rotation
        signer.set_clock(5.0)
        rec = signer.rotate_key(b"new")

        observer = _ident("observer")
        observer.register_peer(AgentId("signer"), rec.new_public_key)
        # observer doesn't know the old key yet -> cannot verify continuity.
        assert not observer.apply_rotation(rec)

        observer2 = _ident("observer2")
        # Seed the old key first, then apply.
        observer2.register_peer(AgentId("signer"), old_pub)
        assert observer2.apply_rotation(rec)
        assert observer2.verify_continuity(AgentId("signer"), rec)

    def test_tampered_continuity_signature_rejected(self) -> None:
        ident = _ident()
        ident.set_clock(5.0)
        rec = ident.rotate_key(b"new")
        rec.continuity_signature = b"\x00" * 64
        assert not ident.verify_continuity(AgentId("a1"), rec)

    def test_retired_key_cannot_authorise_new_successor(self) -> None:
        """A key retired by an *earlier* rotation cannot mint a fresh successor.

        Models a compromised stale key: even with a cryptographically valid
        continuity signature, a peer must not extend the identity chain from a
        key that was already rotated out, or the whole point of rotation is lost.
        """
        from nest_plugins_reference.identity.ed25519_rotating import RotationRecord

        signer = _ident("signer")
        stale_key_id = signer.current_key_id
        signer.set_clock(5.0)
        signer.rotate_key(b"legit-new")  # key0 retired at tick 5, key1 is tip

        # Attacker holds the now-retired key0 and forges a continuity record
        # using a real signature by that stale key (via the public sign_with).
        evil_rec = RotationRecord(
            agent_id=AgentId("signer"),
            old_key_id=stale_key_id,
            new_key_id=KeyId("evil"),
            new_public_key=b"\x11" * 32,
            issued_at=9.0,  # NOT the tick key0 was retired at (5.0)
            continuity_signature=b"",  # filled below with a real stale-key sig
        )
        stale_sig = signer.sign_with(evil_rec.continuity_message(), stale_key_id)
        evil_rec.continuity_signature = stale_sig.value

        # The signature is valid, but key0 is retired -> rejected on the chain-tip
        # guard, and apply_rotation makes no state change.
        assert not signer.verify_continuity(AgentId("signer"), evil_rec)
        assert not signer.apply_rotation(evil_rec)

    def test_retired_key_injection_with_public_retire_tick(self) -> None:
        """The retire tick is public, so matching it must NOT bypass the guard.

        An attacker reads the rotation tick straight from the trace and sets
        ``issued_at`` to it, trying to masquerade as the legitimate self-verify
        case. The guard keys off successor-key membership, not the attacker-
        controllable ``issued_at``, so the injection is still rejected.
        """
        from nest_plugins_reference.identity.ed25519_rotating import RotationRecord

        signer = _ident("signer")
        stale_key_id = signer.current_key_id
        signer.set_clock(5.0)
        signer.rotate_key(b"legit-new")  # key0 retired at the public tick 5.0

        evil_rec = RotationRecord(
            agent_id=AgentId("signer"),
            old_key_id=stale_key_id,
            new_key_id=KeyId("evil"),
            new_public_key=b"\x11" * 32,
            issued_at=5.0,  # == the public retire tick: must not grant a bypass
            continuity_signature=b"",
        )
        evil_rec.continuity_signature = signer.sign_with(
            evil_rec.continuity_message(), stale_key_id
        ).value
        assert not signer.verify_continuity(AgentId("signer"), evil_rec)
        assert not signer.apply_rotation(evil_rec)


class TestDidKeyCompatibility:
    def test_signature_key_id_signed_at_optional(self) -> None:
        # Existing did_key-style callers build Signatures without key_id/signed_at.
        sig = Signature(signer=AgentId("a1"), value=b"x", algorithm="sim-rsa-sha256")
        assert sig.key_id is None
        assert sig.signed_at is None

    def test_register_peer_rejects_private_key(self) -> None:
        ident = _ident()
        with pytest.raises(ValueError, match="public keys only"):
            ident.register_peer(AgentId("a2"), b"pub", private_key=b"priv")

    def test_register_peer_verifies_peer(self) -> None:
        a = _ident("a")
        b = _ident("b")
        a.register_peer(AgentId("b"), b.public_key)
        sig = b.sign(b"from-b")
        # a verifies b's signature as-of b's current window (peer registered now).
        assert a.verify(b"from-b", sig, AgentId("b"), as_of=0.0)


class TestDeterminism:
    def test_same_seed_same_signature(self) -> None:
        a = _ident(seed=b"fixed")
        b = _ident(seed=b"fixed")
        assert a.sign(b"msg").value == b.sign(b"msg").value

    def test_same_seed_same_rotation(self) -> None:
        a = _ident(seed=b"fixed")
        b = _ident(seed=b"fixed")
        a.set_clock(3.0)
        b.set_clock(3.0)
        rec_a = a.rotate_key(b"r")
        rec_b = b.rotate_key(b"r")
        assert rec_a.new_key_id == rec_b.new_key_id
        assert rec_a.continuity_signature == rec_b.continuity_signature

    def test_sign_with_unknown_key_raises(self) -> None:
        ident = _ident()
        with pytest.raises(ValueError, match="no private key"):
            ident.sign_with(b"x", KeyId("deadbeef"))
