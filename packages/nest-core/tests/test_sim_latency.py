# SPDX-License-Identifier: Apache-2.0
"""Integration tests: latency models wired through the simulator.

These tests live in nest-core (not nest-plugins-reference) because they
exercise the simulator's transport directly via the new
``Simulator(latency_model=...)`` parameter, which is the contract.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pytest
from nest_core.sim import Simulator, StateMachineAgent
from nest_core.sim.agent import AgentContext
from nest_core.types import AgentId

# ---------------------------------------------------------------------------
# Small ping-pong harness
# ---------------------------------------------------------------------------


class _Pinger(StateMachineAgent):
    """Sends one ping to ``target`` and echoes any reply once."""

    def __init__(self, target: AgentId) -> None:
        self.target = target
        self.replies = 0

    async def on_start(self, ctx: AgentContext) -> None:
        await ctx.send(self.target, b"ping")

    async def on_message(
        self,
        ctx: AgentContext,
        sender: AgentId,
        payload: bytes,
    ) -> None:
        self.replies += 1


class _Echoer(StateMachineAgent):
    """Replies pong to every ping."""

    async def on_message(
        self,
        ctx: AgentContext,
        sender: AgentId,
        payload: bytes,
    ) -> None:
        if payload == b"ping":
            await ctx.send(sender, b"pong")


def _read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _mean_latency(events: list[dict[str, Any]]) -> float:
    sends: dict[str, float] = {}
    diffs: list[float] = []
    for ev in events:
        cid = ev.get("corr", "")
        if not cid:
            continue
        if ev["kind"] == "send":
            sends[cid] = ev["ts"]
        elif ev["kind"] == "receive" and cid in sends:
            diffs.append(ev["ts"] - sends[cid])
    return statistics.fmean(diffs) if diffs else 0.0


# ---------------------------------------------------------------------------
# Baseline: no latency model -> clock stays at zero (legacy behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_latency_model_keeps_clock_zero(tmp_path: Path) -> None:
    trace = tmp_path / "zero.jsonl"
    sim = Simulator(seed=1, trace_path=trace)
    sim.add_agent(AgentId("p"), _Pinger(AgentId("e")))
    sim.add_agent(AgentId("e"), _Echoer())

    await sim.run(max_ticks=200)

    events = _read_trace(trace)
    assert _mean_latency(events) == 0.0
    assert sim.clock.now == 0.0


# ---------------------------------------------------------------------------
# Constant latency: every hop adds exactly the configured delay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_constant_latency_advances_clock(tmp_path: Path) -> None:
    from nest_plugins_reference.transport.latency import constant_latency

    trace = tmp_path / "constant.jsonl"
    sim = Simulator(seed=1, trace_path=trace, latency_model=constant_latency(0.01))
    sim.add_agent(AgentId("p"), _Pinger(AgentId("e")))
    sim.add_agent(AgentId("e"), _Echoer())

    await sim.run(max_ticks=200)

    events = _read_trace(trace)
    mean = _mean_latency(events)
    # ping -> arrives at 0.01, pong -> arrives at 0.02.  Mean of the two
    # send-to-receive deltas is exactly 0.01.
    assert mean == pytest.approx(0.01, rel=1e-9)  # pyright: ignore[reportUnknownMemberType]
    # The virtual clock advanced past zero.
    assert sim.clock.now >= 0.01


# ---------------------------------------------------------------------------
# Exponential latency: mean roughly matches configuration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exponential_latency_mean_in_range(tmp_path: Path) -> None:
    from nest_plugins_reference.transport.latency import exponential_latency

    target_mean = 0.020
    trace = tmp_path / "expo.jsonl"
    sim = Simulator(seed=42, trace_path=trace, latency_model=exponential_latency(target_mean))
    # Drive lots of traffic to get a stable sample mean.
    agent_ids = [AgentId(f"a{i}") for i in range(20)]
    for i, aid in enumerate(agent_ids):
        sim.add_agent(aid, _Pinger(target=agent_ids[(i + 1) % len(agent_ids)]))
    # Replace half with echoers to keep traffic flowing.
    for i in range(0, len(agent_ids), 2):
        sim._agents[agent_ids[i]].agent = _Echoer()  # type: ignore[attr-defined]

    await sim.run(max_ticks=5_000)

    events = _read_trace(trace)
    observed = _mean_latency(events)
    # Wide tolerance — we just want to confirm the latency is in the
    # right order of magnitude, not assert distribution fit.
    assert 0.5 * target_mean <= observed <= 2.0 * target_mean


# ---------------------------------------------------------------------------
# Determinism: same seed -> byte-identical trace, with a latency model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latency_traces_deterministic(tmp_path: Path) -> None:
    from nest_plugins_reference.transport.latency import exponential_latency

    blobs: list[str] = []
    for run in range(2):
        trace = tmp_path / f"det_{run}.jsonl"
        sim = Simulator(
            seed=2024,
            trace_path=trace,
            latency_model=exponential_latency(0.01),
        )
        sim.add_agent(AgentId("p"), _Pinger(AgentId("e")))
        sim.add_agent(AgentId("e"), _Echoer())
        await sim.run(max_ticks=200)
        blobs.append(trace.read_text())

    assert blobs[0] == blobs[1]
    assert len(blobs[0]) > 0


# ---------------------------------------------------------------------------
# Pair-matrix latency: heterogeneous topology
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pair_matrix_latency(tmp_path: Path) -> None:
    from nest_plugins_reference.transport.latency import pair_matrix_latency

    model = pair_matrix_latency(
        {("p", "e"): 0.005, ("e", "p"): 0.020},
        default=0.0,
    )
    trace = tmp_path / "pair.jsonl"
    sim = Simulator(seed=1, trace_path=trace, latency_model=model)
    sim.add_agent(AgentId("p"), _Pinger(AgentId("e")))
    sim.add_agent(AgentId("e"), _Echoer())

    await sim.run(max_ticks=200)

    events = _read_trace(trace)
    # Two deltas: ping (p->e) = 0.005, pong (e->p) = 0.020.
    deltas: dict[str, float] = {}
    for ev in events:
        cid = ev.get("corr", "")
        if not cid:
            continue
        if ev["kind"] == "send":
            deltas[cid + "_send"] = ev["ts"]
        elif ev["kind"] == "receive":
            send_ts = deltas.get(cid + "_send")
            if send_ts is not None:
                deltas[cid] = ev["ts"] - send_ts
    observed = sorted(v for k, v in deltas.items() if not k.endswith("_send"))
    assert observed == pytest.approx([0.005, 0.020])  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Latency does not break drop / partition logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latency_compatible_with_drop_rate(tmp_path: Path) -> None:
    from nest_plugins_reference.transport.latency import constant_latency

    trace = tmp_path / "drop.jsonl"
    sim = Simulator(
        seed=1,
        trace_path=trace,
        message_drop_rate=0.5,
        latency_model=constant_latency(0.01),
    )
    sim.add_agent(AgentId("p"), _Pinger(AgentId("e")))
    sim.add_agent(AgentId("e"), _Echoer())

    await sim.run(max_ticks=200)

    events = _read_trace(trace)
    kinds = {ev["kind"] for ev in events}
    # No KeyError, no exception; we got *some* trace.
    assert "send" in kinds
