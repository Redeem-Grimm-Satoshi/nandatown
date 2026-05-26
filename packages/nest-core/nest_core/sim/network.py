# SPDX-License-Identifier: Apache-2.0
"""Network model abstraction for the discrete-event simulator.

The default ``in_memory`` transport delivers messages at ``time = now`` — fine
for correctness testing, but useless for any property that depends on
latency, queueing, or backpressure. ``NetworkModel`` is the seam: given a
send event, it returns the virtual time at which the message should be
delivered (or ``None`` to drop the message).

The default :class:`ZeroLatencyNetworkModel` reproduces the existing
zero-latency semantics so simulations that don't configure a network model
behave exactly as before.

Plugin transports can ship their own :class:`NetworkModel` subclass and
expose it via a ``network_model`` attribute; the scenario runner picks it
up automatically and wires it into the simulator.

Example::

    class FixedDelayNetwork(NetworkModel):
        def schedule(self, sender, target, payload_size, t_now, rng):
            return t_now + 0.010  # 10 ms per hop, no jitter, no drops

    sim = Simulator(seed=42, network_model=FixedDelayNetwork())
"""

from __future__ import annotations

import random
from typing import Protocol, runtime_checkable

from nest_core.types import AgentId


@runtime_checkable
class NetworkModel(Protocol):
    """Pluggable per-hop scheduling for the simulator's transport.

    Implementations must be deterministic given the supplied ``rng``: the
    simulator passes its own failure-injection RNG so that traces remain
    reproducible across runs with the same seed.

    Example::

        class MyNetwork:
            def schedule(self, sender, target, payload_size, t_now, rng):
                return t_now + rng.uniform(0.001, 0.005)
    """

    def schedule(
        self,
        sender: AgentId,
        target: AgentId,
        payload_size: int,
        t_now: float,
        rng: random.Random,
    ) -> float | None:
        """Return the delivery time for a message, or ``None`` to drop it.

        The returned time must be ``>= t_now``. Returning ``None`` signals
        a transport-level drop; the simulator records a ``dropped`` event
        with reason ``"network"``.

        Example::

            t_deliver = model.schedule(a1, a2, 128, ctx.time, rng)
        """
        ...


class ZeroLatencyNetworkModel:
    """Default model: every message is delivered at the current simulation time.

    This preserves the existing in-memory behavior and ensures backwards
    compatibility for traces and validators that assume zero-latency
    delivery.

    Example::

        sim = Simulator(seed=0, network_model=ZeroLatencyNetworkModel())
    """

    def schedule(
        self,
        sender: AgentId,  # noqa: ARG002 — part of the protocol surface
        target: AgentId,  # noqa: ARG002
        payload_size: int,  # noqa: ARG002
        t_now: float,
        rng: random.Random,  # noqa: ARG002
    ) -> float | None:
        return t_now


# Verify the default satisfies the protocol at import time.
_proto_check: type[NetworkModel] = ZeroLatencyNetworkModel  # noqa: F841
