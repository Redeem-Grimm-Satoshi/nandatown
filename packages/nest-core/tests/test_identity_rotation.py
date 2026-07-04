# SPDX-License-Identifier: Apache-2.0
"""Tests for the identity_rotation scenario and its adversarial validator.

Proves the validator FAILS against ``did_key`` and PASSES against
``ed25519_rotating`` end-to-end, that both attacks are caught at the trace
level, and that the scenario is deterministic.

Example::

    pytest packages/nest-core/tests/test_identity_rotation.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig
from nest_core.validators import (
    validate_events,
    validate_identity_rotation_occurred,
    validate_identity_rotation_signatures,
    validate_trace,
)

type Event = dict[str, Any]


def _send(agent: str, to: str, msg: str, ts: float) -> Event:
    return {"ts": ts, "agent": agent, "kind": "send", "to": to, "msg": msg}


# ---------------------------------------------------------------------------
# Unit-level validator tests (synthetic traces)
# ---------------------------------------------------------------------------


class TestValidatorWindows:
    def _honest_trace(self) -> list[Event]:
        # key K0 valid [0,2); K1 valid [2, inf). Rotation at tick 2.
        return [
            _send("s0", "aud", "signed:s0:K0:0.0:ok", ts=0.0),
            _send("s0", "aud", "signed:s0:K0:1.0:ok", ts=1.0),
            _send("s0", "aud", "rotate:s0:K0:K1:2.0", ts=2.0),
            _send("s0", "aud", "signed:s0:K1:2.0:ok", ts=2.0),
            _send("s0", "aud", "signed:s0:K1:3.0:ok", ts=3.0),
        ]

    def test_honest_trace_passes(self) -> None:
        events = self._honest_trace()
        assert validate_identity_rotation_occurred(events)[0].passed
        assert validate_identity_rotation_signatures(events)[0].passed

    def test_post_rotation_forgery_rejected(self) -> None:
        # forge: old key K0 used at observed ts=3 (>= rotated_out=2) -> invalid.
        events = [*self._honest_trace(), _send("a", "aud", "signed:a:K0:3.0:forge", ts=3.0)]
        # The attack line is supposed to be window-invalid; validator PASSES
        # (the protocol correctly rejected it).
        res = validate_identity_rotation_signatures(events)[0]
        assert res.passed, res.detail
        assert "1 attacks rejected" in res.detail

    def test_backdating_rejected(self) -> None:
        # backdate: new key K1 with claimed tick 0.0 (< issued_at=2) -> invalid.
        events = [*self._honest_trace(), _send("a", "aud", "signed:a:K1:0.0:backdate", ts=3.0)]
        res = validate_identity_rotation_signatures(events)[0]
        assert res.passed, res.detail

    def test_validator_fails_when_attack_accepted(self) -> None:
        # A forge line that lands inside a valid window (key K1 at its own tick)
        # would mean the protocol FAILED to reject it -> validator FAILS.
        events = [*self._honest_trace(), _send("a", "aud", "signed:a:K1:3.0:forge", ts=3.0)]
        res = validate_identity_rotation_signatures(events)[0]
        assert not res.passed
        assert "accepted" in res.detail

    def test_validator_fails_when_honest_outside_window(self) -> None:
        events = [_send("s0", "aud", "signed:s0:K0:9.0:ok", ts=9.0)]
        # K0 seeded as [0, inf) but no rotation occurred.
        assert not validate_identity_rotation_occurred(events)[0].passed

    def test_did_key_style_lines_fail_without_crashing(self) -> None:
        # did_key emits key_id "None" and no rotate lines.
        events = [
            _send("s0", "aud", "signed:s0:None:0.0:ok", ts=0.0),
            _send("s0", "aud", "signed:s0:None:1.0:ok", ts=1.0),
        ]
        occurred = validate_identity_rotation_occurred(events)[0]
        sigs = validate_identity_rotation_signatures(events)[0]
        assert not occurred.passed
        assert not sigs.passed

    def test_registry_dispatch(self) -> None:
        events = self._honest_trace()
        results = validate_events(events, "identity_rotation")
        assert len(results) == 2
        assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# End-to-end scenario tests
# ---------------------------------------------------------------------------

_YAML = Path(__file__).parent.parent.parent.parent / "scenarios" / "identity_rotation.yaml"


def _config(trace: Path, identity: str) -> ScenarioConfig:
    config = ScenarioConfig.from_yaml(_YAML)
    config.layers.identity = identity
    config.output.trace = str(trace)
    return config


class TestScenarioEndToEnd:
    @pytest.mark.asyncio
    async def test_passes_against_ed25519_rotating(self, tmp_path: Path) -> None:
        trace = tmp_path / "rot.jsonl"
        runner = ScenarioRunner(_config(trace, "ed25519_rotating"))
        result = await runner.run()
        assert result.exists()

        results = validate_trace(result, "identity_rotation")
        assert all(r.passed for r in results), [str(r) for r in results]
        # Sanity: at least one rotation and both attack kinds present in trace.
        text = result.read_text()
        assert "rotate:" in text
        assert ":forge" in text
        assert ":backdate" in text

    @pytest.mark.asyncio
    async def test_fails_against_did_key_without_crashing(self, tmp_path: Path) -> None:
        trace = tmp_path / "didkey.jsonl"
        runner = ScenarioRunner(_config(trace, "did_key"))
        # Must NOT raise — did_key has no rotate_key; agents capability-gate it.
        result = await runner.run()
        assert result.exists()

        results = validate_trace(result, "identity_rotation")
        assert not all(r.passed for r in results)
        # No rotations should have happened under did_key.
        assert "rotate:" not in result.read_text()

    @pytest.mark.asyncio
    async def test_deterministic(self, tmp_path: Path) -> None:
        traces: list[str] = []
        for i in range(2):
            trace = tmp_path / f"det-{i}.jsonl"
            runner = ScenarioRunner(_config(trace, "ed25519_rotating"))
            await runner.run()
            traces.append(trace.read_text())
        assert traces[0] == traces[1]
        assert len(traces[0]) > 0
