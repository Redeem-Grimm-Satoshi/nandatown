# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests for the NetworkModel hook in the Tier 1 simulator.

Verifies that:
1. The default zero-latency model preserves backwards-compatible behavior.
2. A custom NetworkModel actually shifts the virtual clock and surfaces
   in mean_latency / duration.
3. Network-level drops (returning None) produce trace ``dropped`` events
   with a ``reason`` field distinct from scenario-level failure injection.
4. The model is invoked deterministically — same seed, same trace.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from nest_core.sim import (
    NetworkModel,
    Simulator,
    StateMachineAgent,
    ZeroLatencyNetworkModel,
)
from nest_core.sim.agent import AgentContext
from nest_core.types import AgentId


class _PingOnce(StateMachineAgent):
    """Sends one ping on start, records every message it receives."""

    def __init__(self, target: AgentId) -> None:
        self.target = target
        self.received: list[tuple[float, bytes]] = []

    async def on_start(self, ctx: AgentContext) -> None:
        if self.target != ctx.agent_id:
            await ctx.send(self.target, b"ping")

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        del sender
        self.received.append((ctx.time, payload))


class _FixedDelayNetwork:
    """Adds a constant 0.5-second delay to every send."""

    def schedule(
        self,
        sender: AgentId,  # noqa: ARG002
        target: AgentId,  # noqa: ARG002
        payload_size: int,  # noqa: ARG002
        t_now: float,
        rng: random.Random,  # noqa: ARG002
    ) -> float | None:
        return t_now + 0.5


class _DropEverythingNetwork:
    """Drops every send to A2; lets others through with no delay."""

    def schedule(
        self,
        sender: AgentId,  # noqa: ARG002
        target: AgentId,
        payload_size: int,  # noqa: ARG002
        t_now: float,
        rng: random.Random,  # noqa: ARG002
    ) -> float | None:
        if target == AgentId("a2"):
            return None
        return t_now


def _read_trace(p: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in p.read_text().splitlines()]


class TestDefaultBehavior:
    @pytest.mark.asyncio
    async def test_no_network_model_means_zero_latency(self, tmp_path: Path) -> None:
        trace = tmp_path / "out.jsonl"
        sim = Simulator(seed=0, trace_path=trace)
        sim.add_agent(AgentId("a1"), _PingOnce(AgentId("a2")))
        sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
        await sim.run(max_ticks=100)
        assert sim.clock.now == 0.0

    @pytest.mark.asyncio
    async def test_explicit_zero_latency_matches_default(self, tmp_path: Path) -> None:
        trace = tmp_path / "out.jsonl"
        sim = Simulator(seed=0, trace_path=trace, network_model=ZeroLatencyNetworkModel())
        sim.add_agent(AgentId("a1"), _PingOnce(AgentId("a2")))
        sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
        await sim.run(max_ticks=100)
        assert sim.clock.now == 0.0


class TestLatencyAdvancesClock:
    @pytest.mark.asyncio
    async def test_fixed_delay_shows_up_in_clock(self, tmp_path: Path) -> None:
        trace = tmp_path / "out.jsonl"
        sim = Simulator(
            seed=0,
            trace_path=trace,
            network_model=_FixedDelayNetwork(),
        )
        sim.add_agent(AgentId("a1"), _PingOnce(AgentId("a2")))
        sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
        await sim.run(max_ticks=100)
        # Two pings — each carries a 0.5 s hop, so the clock should reach 0.5.
        assert sim.clock.now >= 0.5

    @pytest.mark.asyncio
    async def test_receive_events_carry_post_delay_timestamp(self, tmp_path: Path) -> None:
        trace = tmp_path / "out.jsonl"
        sim = Simulator(
            seed=0,
            trace_path=trace,
            network_model=_FixedDelayNetwork(),
        )
        sim.add_agent(AgentId("a1"), _PingOnce(AgentId("a2")))
        sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
        await sim.run(max_ticks=100)

        events = _read_trace(trace)
        sends = [e for e in events if e["kind"] == "send"]
        receives = [e for e in events if e["kind"] == "receive"]
        assert sends and receives

        # For each correlation_id, receive.ts should be send.ts + 0.5.
        send_by_corr = {e["corr"]: e["ts"] for e in sends}
        for r in receives:
            assert r["ts"] == pytest.approx(send_by_corr[r["corr"]] + 0.5, abs=1e-9)


class TestNetworkDrop:
    @pytest.mark.asyncio
    async def test_drop_recorded_in_trace(self, tmp_path: Path) -> None:
        trace = tmp_path / "out.jsonl"
        sim = Simulator(
            seed=0,
            trace_path=trace,
            network_model=_DropEverythingNetwork(),
        )
        sim.add_agent(AgentId("a1"), _PingOnce(AgentId("a2")))
        sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
        await sim.run(max_ticks=100)

        events = _read_trace(trace)
        dropped = [e for e in events if e["kind"] == "dropped"]
        # a1 -> a2 ping should be dropped; a2's send to a1 still arrives.
        assert any(e.get("from") == "a1" and e.get("reason") == "network" for e in dropped)
        receives = [e for e in events if e["kind"] == "receive"]
        # a1 should still receive a2's ping.
        assert any(r["agent"] == "a1" for r in receives)

    @pytest.mark.asyncio
    async def test_failure_injection_drops_carry_distinct_reason(self, tmp_path: Path) -> None:
        trace = tmp_path / "out.jsonl"
        sim = Simulator(
            seed=42,
            trace_path=trace,
            message_drop_rate=1.0,  # drop everything at the failure layer
        )
        sim.add_agent(AgentId("a1"), _PingOnce(AgentId("a2")))
        sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
        await sim.run(max_ticks=100)

        events = _read_trace(trace)
        dropped = [e for e in events if e["kind"] == "dropped"]
        assert dropped
        assert all(e.get("reason") == "failure_injection" for e in dropped)


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_seed_same_trace(self, tmp_path: Path) -> None:
        from nest_plugins_reference.transport.realistic import RealisticNetwork

        traces = []
        for run_idx in range(2):
            trace = tmp_path / f"out{run_idx}.jsonl"
            sim = Simulator(
                seed=2024,
                trace_path=trace,
                network_model=RealisticNetwork(
                    base_latency_ms=10.0,
                    jitter_sigma=0.4,
                    bandwidth_bps=1_000_000.0,
                    loss_rate=0.05,
                ),
            )
            sim.add_agent(AgentId("a1"), _PingOnce(AgentId("a2")))
            sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
            await sim.run(max_ticks=200)
            traces.append(trace.read_text())

        assert traces[0] == traces[1]


class TestProtocolHook:
    def test_network_model_protocol_runtime_check(self) -> None:
        m: NetworkModel = _FixedDelayNetwork()
        assert hasattr(m, "schedule")


class _Chatterbox(StateMachineAgent):
    """Spams N messages on start to stress the egress queue."""

    def __init__(self, target: AgentId, n: int, size: int) -> None:
        self.target = target
        self.n = n
        self.size = size

    async def on_start(self, ctx: AgentContext) -> None:
        if self.target == ctx.agent_id:
            return
        payload = b"x" * self.size
        for _ in range(self.n):
            await ctx.send(self.target, payload)


class TestRealisticEndToEnd:
    @pytest.mark.asyncio
    async def test_queueing_observed_in_mean_latency(self, tmp_path: Path) -> None:
        from nest_core.metrics import compute_metrics
        from nest_plugins_reference.transport.realistic import RealisticNetwork

        trace = tmp_path / "out.jsonl"
        # 1 Mbps, 1 kB messages => 8 ms serialization per message.
        # 100 messages back-to-back => last one arrives ~ 800 ms after send.
        sim = Simulator(
            seed=0,
            trace_path=trace,
            network_model=RealisticNetwork(
                base_latency_ms=5.0,
                jitter_sigma=0.0,
                bandwidth_bps=1_000_000.0,
                loss_rate=0.0,
            ),
        )
        sim.add_agent(AgentId("a1"), _Chatterbox(AgentId("a2"), n=100, size=1000))
        sim.add_agent(AgentId("a2"), _PingOnce(AgentId("a1")))
        await sim.run(max_ticks=10_000)

        metrics = compute_metrics(trace, ["mean_latency", "duration", "message_count"])
        # Each message gets at least 5 ms base; the last queued one is much
        # higher. The average should comfortably exceed 5 ms.
        assert metrics["mean_latency"] > 0.005
        assert metrics["duration"] > 0.0
        assert metrics["message_count"] >= 100
