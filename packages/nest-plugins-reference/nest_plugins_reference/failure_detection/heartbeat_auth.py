# SPDX-License-Identifier: Apache-2.0
"""Authenticated heartbeat wire format and pluggable heartbeat verifiers.

A liveness observer that reads heartbeats off a broadcast medium has to answer
one question about every beat it receives: *did the peer this beat claims to be
from actually send it?*  Trusting the id printed in the payload is the naive
answer, and it is exactly the spoofing hole a Byzantine peer exploits to keep a
crashed peer looking alive.  This module packages the authenticated wire format
and two swappable verifiers so any scenario -- not just failure detection -- can
reuse them and pick a verifier the same way it picks any other component.

The wire format is ``FDHB|<id>|<ts>|<sig-hex>``: the sender id, the emission
timestamp, and a signature over ``FDHB|<id>|<ts>``.  It is deterministic (the
timestamp is quantized to 6 dp and the signature is reconstructed from the raw
wire text, never a re-parsed float), so traces replay byte-for-byte.

A :class:`HeartbeatAuthenticator` turns a received payload into an accepted
``(peer, ts)`` or rejects it:

* :class:`SignedHeartbeatAuthenticator` requires a valid signature by the
  claimed peer's registered key and a strictly-increasing, non-future
  timestamp, so fabricated and replayed beats are both rejected.
* :class:`TrustingHeartbeatAuthenticator` believes the claimed id outright.  It
  is the naive baseline a discriminating scenario runs as its foil.

Swapping one for the other is how the failure-detection forgery scenario turns
"does authentication matter?" into a component swap rather than a code branch,
mirroring how it swaps ``phi_accrual`` for ``heartbeat`` to test the detector.

Example::

    auth = SignedHeartbeatAuthenticator(observer_identity)
    beat = heartbeat_payload(peer_identity, AgentId("peer-0"), now=12.5)
    accepted = auth.accept(beat, now=12.5)  # -> (AgentId("peer-0"), 12.5)
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from nest_core.types import AgentId, Signature

HB_PREFIX = "FDHB|"
"""Marker prefix identifying a heartbeat broadcast; the rest is ``<id>|<ts>|<sig>``."""

HB_ALGORITHM = "sim-rsa-sha256"
"""Algorithm tag stamped on reconstructed heartbeat signatures.

The reference identity plugins verify by key material and ignore this field; it
is carried for trace forensics only.
"""


def heartbeat_payload(identity: Any, agent_id: AgentId, now: float) -> bytes:
    """Return a signed heartbeat payload ``FDHB|<id>|<ts>|<sig-hex>``.

    The signature covers ``FDHB|<id>|<ts>`` exactly as serialized, so a verifier
    can rebuild the signed bytes from the wire text without float round-tripping.
    When *identity* is ``None`` the unsigned prefix form is emitted (usable only
    by a trusting observer).

    Example::

        payload = heartbeat_payload(identity, AgentId("peer-0"), 12.5)
    """
    base = f"{HB_PREFIX}{agent_id}|{round(now, 6)}"
    if identity is None:
        return base.encode()
    sig = identity.sign(base.encode())
    return f"{base}|{sig.value.hex()}".encode()


def claimed_peer(payload: bytes) -> AgentId | None:
    """Return the peer id a heartbeat payload *claims*, with no authentication.

    This is the trusting parse: it believes whatever id the payload names, which
    is exactly the spoofable behavior the forgery scenario attacks.

    Example::

        peer = claimed_peer(b"FDHB|peer-0|12.5|abcd")
    """
    text = payload.decode("utf-8", "replace")
    if not text.startswith(HB_PREFIX):
        return None
    claimed = text[len(HB_PREFIX) :].split("|", 1)[0]
    if not claimed:
        return None
    return AgentId(claimed)


class HeartbeatAuthenticator(Protocol):
    """Decide whether a received heartbeat payload is an acceptable observation.

    ``name`` identifies the verifier for selection and logging; ``verifies`` is
    ``True`` when the verifier authenticates beats (used by callers to annotate
    the trace).  ``accept`` returns the accepted ``(peer, ts)`` or ``None``.

    Example::

        auth: HeartbeatAuthenticator = SignedHeartbeatAuthenticator(identity)
    """

    name: str
    verifies: bool

    def accept(self, payload: bytes, *, now: float) -> tuple[AgentId, float] | None:
        """Return ``(peer, ts)`` if the beat is acceptable at *now*, else ``None``.

        Example::

            accepted = auth.accept(payload, now=12.5)
        """
        ...


class TrustingHeartbeatAuthenticator:
    """Accept a heartbeat on the strength of its *claimed* id alone.

    The naive baseline: no signature check, no freshness check.  A Byzantine
    peer that broadcasts ``FDHB|victim|...`` is believed, so this verifier lets
    forged liveness through -- which is the whole point of running it as the
    foil the signed verifier is measured against.

    Example::

        auth = TrustingHeartbeatAuthenticator()
        auth.accept(b"FDHB|peer-0|12.5|ab", now=12.5)  # -> (AgentId("peer-0"), 12.5)
    """

    name = "trusting"
    verifies = False

    def accept(self, payload: bytes, *, now: float) -> tuple[AgentId, float] | None:
        """Return ``(claimed_peer, now)`` for any heartbeat-shaped payload.

        Example::

            accepted = auth.accept(payload, now=ctx.time)
        """
        peer = claimed_peer(payload)
        if peer is None:
            return None
        return peer, now


class SignedHeartbeatAuthenticator:
    """Accept a heartbeat only if it is authentically signed and fresh.

    Rejects the payload unless every check passes:

    * well-formed ``FDHB|<id>|<ts>|<sig-hex>`` wire format with a finite
      timestamp;
    * the signed timestamp is not from the future and is strictly newer than the
      last accepted heartbeat from that peer (defeats replay);
    * the signature verifies against the *claimed* peer's registered public key
      (defeats fabrication -- a forger signing with its own key fails).

    The last-accepted timestamp per peer is held internally and advanced on every
    acceptance, so the verifier owns its own replay state.  Verification never
    consults transport metadata, so it holds even on a transport whose sender
    field cannot be trusted.

    Example::

        auth = SignedHeartbeatAuthenticator(observer_identity)
        auth.accept(genuine_beat, now=12.5)   # -> (peer, 12.5)
        auth.accept(genuine_beat, now=99.0)   # -> None  (replayed)
    """

    name = "signed"
    verifies = True

    def __init__(self, identity: Any) -> None:
        self._identity = identity
        self._last_ts: dict[AgentId, float] = {}

    def accept(self, payload: bytes, *, now: float) -> tuple[AgentId, float] | None:
        """Return ``(peer, ts)`` if signature and freshness pass, else ``None``.

        Example::

            accepted = auth.accept(payload, now=ctx.time)
        """
        text = payload.decode("utf-8", "replace")
        if not text.startswith(HB_PREFIX):
            return None
        fields = text[len(HB_PREFIX) :].split("|")
        if len(fields) != 3:
            return None
        claimed, ts_text, sig_hex = fields
        if not claimed:
            return None
        try:
            ts = float(ts_text)
            sig_bytes = bytes.fromhex(sig_hex)
        except ValueError:
            return None
        # A non-finite timestamp (nan/inf) would slip the IEEE-754 comparisons
        # below, so reject it outright.  Genuine beats carry ``round(now, 6)``.
        if not math.isfinite(ts):
            return None
        peer = AgentId(claimed)
        # The signed ts is quantized to 6 dp, so it can round a hair above the
        # observer's exact ``now`` on the same zero-latency tick; compare against
        # the same quantum rather than raw ``now`` so genuine beats are not read
        # as future-dated.  Replays are still caught by the strict freshness check.
        if ts > round(now, 6) or ts <= self._last_ts.get(peer, float("-inf")):
            return None
        if self._identity is None:
            return None
        base = f"{HB_PREFIX}{claimed}|{ts_text}"
        sig = Signature(signer=peer, value=sig_bytes, algorithm=HB_ALGORITHM)
        if not self._identity.verify(base.encode(), sig, peer):
            return None
        self._last_ts[peer] = ts
        return peer, ts


def make_heartbeat_authenticator(name: str, identity: Any) -> HeartbeatAuthenticator:
    """Build the heartbeat authenticator named *name*.

    ``"signed"`` returns a :class:`SignedHeartbeatAuthenticator` bound to
    *identity*; ``"trusting"`` returns a :class:`TrustingHeartbeatAuthenticator`
    (which ignores *identity*).  Any other name raises ``ValueError`` so a
    misconfigured scenario fails fast rather than silently disabling
    authentication.

    Example::

        auth = make_heartbeat_authenticator("signed", observer_identity)
    """
    if name == "signed":
        return SignedHeartbeatAuthenticator(identity)
    if name == "trusting":
        return TrustingHeartbeatAuthenticator()
    msg = f"unknown heartbeat authenticator {name!r} (expected 'signed' or 'trusting')"
    raise ValueError(msg)


# Verify both verifiers structurally satisfy the protocol at import.
_check_signed: type[HeartbeatAuthenticator] = SignedHeartbeatAuthenticator  # noqa: F841
_check_trusting: type[HeartbeatAuthenticator] = TrustingHeartbeatAuthenticator  # noqa: F841
