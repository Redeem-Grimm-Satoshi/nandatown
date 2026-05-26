# SPDX-License-Identifier: Apache-2.0
"""In-memory transport wired to the simulator's event queue.

Delivery time is delegated to a :class:`NetworkModel` so that plugins can
inject per-hop latency, jitter, queueing, and packet loss without
forking the simulator. The default model is zero-latency, preserving the
existing behavior.

Example::

    transport = InMemoryTransport(agent_id, event_queue, clock)
    await transport.send(AgentId("a2"), b"hello")
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from nest_core.sim.network import NetworkModel, ZeroLatencyNetworkModel
from nest_core.types import AgentId, CorrelationId, TransportCapabilities

if TYPE_CHECKING:
    from nest_core.sim.clock import VirtualClock
    from nest_core.sim.events import EventQueue


class InMemoryTransport:
    """Transport that routes messages through the simulator's event queue.

    Example::

        transport = InMemoryTransport(AgentId("a1"), queue, clock)
        await transport.send(AgentId("a2"), b"data")
    """

    capabilities = TransportCapabilities(
        supports_streaming=False,
        ordered=True,
        reliable=True,
    )

    def __init__(
        self,
        agent_id: AgentId,
        event_queue: EventQueue,
        clock: VirtualClock,
        all_agents: list[AgentId] | None = None,
        network_model: NetworkModel | None = None,
        network_rng: random.Random | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._queue = event_queue
        self._clock = clock
        self.all_agents = all_agents or []
        self._network_model: NetworkModel = network_model or ZeroLatencyNetworkModel()
        # Falling back to a deterministic Random(0) keeps standalone uses of the
        # transport reproducible. The simulator overrides this with its own
        # failure-injection RNG so traces stay byte-identical across runs.
        self._network_rng = network_rng if network_rng is not None else random.Random(0)

    def set_network(self, model: NetworkModel, rng: random.Random) -> None:
        """Replace the network model and RNG (used by the simulator at wire-up).

        Example::

            transport.set_network(RealisticNetwork(...), failure_rng)
        """
        self._network_model = model
        self._network_rng = rng

    async def send(
        self,
        to: AgentId,
        payload: bytes,
        correlation_id: CorrelationId | None = None,
    ) -> tuple[float, bool]:
        """Enqueue a message delivery event.

        Returns ``(delivery_time, accepted)`` so the caller (the simulator)
        can record drop events when the network model rejects the message.

        Example::

            t, ok = await transport.send(AgentId("a2"), b"hello")
        """
        from nest_core.sim.events import Event

        t_deliver = self._network_model.schedule(
            sender=self._agent_id,
            target=to,
            payload_size=len(payload),
            t_now=self._clock.now,
            rng=self._network_rng,
        )
        if t_deliver is None:
            return (self._clock.now, False)
        if t_deliver < self._clock.now:
            # Network models must respect the arrow of time; clamp defensively
            # rather than corrupt the event queue.
            t_deliver = self._clock.now

        self._queue.push(
            Event(
                time=t_deliver,
                kind="deliver",
                agent_id=to,
                target_id=self._agent_id,
                payload=payload,
                correlation_id=correlation_id,
            )
        )
        return (t_deliver, True)

    async def receive(self) -> tuple[AgentId, bytes]:
        """Not used in Tier 1 — the simulator pushes events to agents.

        Example::

            # Not applicable in simulation mode
        """
        raise NotImplementedError("Tier 1 transport is push-based via the event queue")

    async def broadcast(
        self,
        payload: bytes,
        correlation_id: CorrelationId | None = None,
    ) -> list[tuple[AgentId, float, bool]]:
        """Broadcast to all known agents.

        Returns a list of ``(target, delivery_time, accepted)`` so the
        simulator can record per-target trace events.

        Example::

            results = await transport.broadcast(b"announcement")
        """
        results: list[tuple[AgentId, float, bool]] = []
        for aid in self.all_agents:
            if aid != self._agent_id:
                t, ok = await self.send(aid, payload, correlation_id=correlation_id)
                results.append((aid, t, ok))
        return results
