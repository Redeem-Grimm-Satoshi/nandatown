# SPDX-License-Identifier: Apache-2.0
"""End-to-end FAIL/PASS gate: byzantine gossip scenarios vs the reference plugin.

Task 6's deliverable: run each of the three adversarial scenarios
(``gossip_byzantine_forgery``, ``gossip_signed_equivocation``,
``gossip_eclipse``) under both ``registry: byzantine_gossip`` and
``registry: gossip`` -- same YAML, same seed, only ``layers.registry``
differs -- and prove the three mandated validators
(``nest_plugins_reference.validators.registry_byzantine_validators``) PASS
for ``byzantine_gossip`` and at least one FAILs for the reference ``gossip``
plugin, deterministically across seeds 42, 7, 1337.

The headline is ``gossip_signed_equivocation``: every card in that scenario
is validly signed by its real publisher key (see
``EquivocatorDriverAgent``) -- the failure it proves is not "signatures are
missing," it is "a registration-signing-only defense (prior art ``#67``)
cannot catch a publisher who signs two conflicting writes."
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig
from nest_core.types import AgentId, Query
from nest_plugins_reference.registry.byzantine_gossip import canonical_write_bytes
from nest_plugins_reference.validators.registry_byzantine_validators import (
    EquivocationView,
    check_no_eclipse,
    check_no_equivocation_accepted,
    check_no_forged_card_in_view,
)

_SCENARIOS_DIR = Path(__file__).parent.parent.parent.parent / "scenarios"

_SEEDS = [42, 7, 1337]


def _config(yaml_name: str, registry_plugin: str, trace: Path, seed: int) -> ScenarioConfig:
    """Load a scenario YAML, override its registry plugin/seed/trace path.

    Example::

        config = _config("gossip_byzantine_forgery.yaml", "gossip", trace, 42)
    """
    config = ScenarioConfig.from_yaml(_SCENARIOS_DIR / yaml_name)
    config.layers.registry = registry_plugin
    config.output.trace = str(trace)
    config.seed = seed
    return config


async def _run(yaml_name: str, registry_plugin: str, trace: Path, seed: int) -> dict[str, Any]:
    """Run a scenario under ``registry_plugin``; return the resolved plugins dict.

    Example::

        plugins = await _run("gossip_eclipse.yaml", "byzantine_gossip", trace, 42)
    """
    runner = ScenarioRunner(_config(yaml_name, registry_plugin, trace, seed))
    await runner.run()
    return runner.resolved_plugins


async def _collect_cards(
    registries: dict[AgentId, Any], honest_ids: set[AgentId]
) -> dict[AgentId, Any]:
    """Pull one representative live ``AgentCard`` per published id from the honest views.

    Example::

        cards = await _collect_cards(registries, honest_ids)
    """
    cards: dict[AgentId, Any] = {}
    for aid in honest_ids:
        for card in await registries[aid].lookup(Query()):
            cards.setdefault(card.agent_id, card)
    return cards


async def _equivocation_views(
    registries: dict[AgentId, Any], honest_ids: set[AgentId]
) -> EquivocationView:
    """Build the content-aware ``EquivocationView`` shape from live registries.

    Example::

        views = await _equivocation_views(registries, honest_ids)
    """
    out: EquivocationView = {}
    for aid in honest_ids:
        reg = registries[aid]
        snapshot = reg.view_snapshot()
        cards_by_id = {c.agent_id: c for c in await reg.lookup(Query())}
        per_viewer: dict[AgentId, tuple[int, bool, str]] = {}
        for publisher_id, (version, _writer, tombstone) in snapshot.items():
            card = cards_by_id.get(publisher_id)
            if card is None:
                continue  # tombstoned/absent; not exercised by this scenario
            content_hash = hashlib.sha256(
                canonical_write_bytes(card, version, tombstone)
            ).hexdigest()
            per_viewer[publisher_id] = (version, tombstone, content_hash)
        out[aid] = per_viewer
    return out


def _equivocation_ledgers(
    registries: dict[AgentId, Any],
) -> dict[AgentId, list[tuple[AgentId, int]]]:
    """Read each registry's ``equivocations`` ledger, defaulting to empty for plugins without one.

    Example::

        ledgers = _equivocation_ledgers(registries)
    """
    return {aid: list(getattr(reg, "equivocations", [])) for aid, reg in registries.items()}


async def _validator_verdicts(plugins: dict[str, Any]) -> dict[str, bool]:
    """Run all three mandated validators against one completed scenario run.

    Example::

        verdicts = await _validator_verdicts(plugins)
        assert verdicts["forged"]
    """
    registries: dict[AgentId, Any] = plugins["_byzantine_registries"]
    identities: dict[AgentId, Any] = plugins["_byzantine_identities"]
    honest_ids: set[AgentId] = plugins["_honest_ids"]
    byzantine_ids: set[AgentId] = plugins["_byzantine_ids"]

    views = {aid: registries[aid].view_snapshot() for aid in honest_ids}
    cards = await _collect_cards(registries, honest_ids)
    forged_report = check_no_forged_card_in_view(views, identities, cards)

    equivocation_views = await _equivocation_views(registries, honest_ids)
    ledgers = _equivocation_ledgers(registries)
    equivocation_report = check_no_equivocation_accepted(ledgers, equivocation_views)

    eclipse_report = check_no_eclipse(views, honest_ids, byzantine_ids)

    return {
        "forged": forged_report.passed,
        "equivocation": equivocation_report.passed,
        "eclipse": eclipse_report.passed,
    }


# ---------------------------------------------------------------------------
# Scenario 1: forgery
# ---------------------------------------------------------------------------


class TestForgeryScenario:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", _SEEDS)
    async def test_byzantine_gossip_passes_all_three(self, tmp_path: Path, seed: int) -> None:
        trace = tmp_path / f"forgery_byz_{seed}.jsonl"
        plugins = await _run("gossip_byzantine_forgery.yaml", "byzantine_gossip", trace, seed)
        verdicts = await _validator_verdicts(plugins)
        assert verdicts == {"forged": True, "equivocation": True, "eclipse": True}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", _SEEDS)
    async def test_reference_gossip_fails_forged_check(self, tmp_path: Path, seed: int) -> None:
        trace = tmp_path / f"forgery_ref_{seed}.jsonl"
        plugins = await _run("gossip_byzantine_forgery.yaml", "gossip", trace, seed)
        verdicts = await _validator_verdicts(plugins)
        assert verdicts["forged"] is False


# ---------------------------------------------------------------------------
# Scenario 2: signed equivocation -- THE NOVELTY PROOF
# ---------------------------------------------------------------------------


class TestSignedEquivocationScenario:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", _SEEDS)
    async def test_byzantine_gossip_passes_all_three(self, tmp_path: Path, seed: int) -> None:
        trace = tmp_path / f"equiv_byz_{seed}.jsonl"
        plugins = await _run("gossip_signed_equivocation.yaml", "byzantine_gossip", trace, seed)
        verdicts = await _validator_verdicts(plugins)
        assert verdicts == {"forged": True, "equivocation": True, "eclipse": True}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", _SEEDS)
    async def test_reference_gossip_fails_equivocation_check(
        self, tmp_path: Path, seed: int
    ) -> None:
        trace = tmp_path / f"equiv_ref_{seed}.jsonl"
        plugins = await _run("gossip_signed_equivocation.yaml", "gossip", trace, seed)
        verdicts = await _validator_verdicts(plugins)
        # check_no_forged_card_in_view also FAILs here, but for an unrelated,
        # structural reason: plain `gossip` never signs ANYTHING, including
        # honest agents' own registrations, so every honest card is
        # "unsigned" regardless of this scenario's attack (see that
        # validator's docstring). The invariant THIS scenario proves is
        # narrower and does not depend on that: the equivocator's two cards
        # are both genuinely, validly signed (nothing forged about them),
        # yet the network still silently diverges on their content with no
        # record of it -- check_no_equivocation_accepted is what must FAIL.
        assert verdicts["equivocation"] is False


# ---------------------------------------------------------------------------
# Scenario 3: eclipse
# ---------------------------------------------------------------------------


class TestEclipseScenario:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", _SEEDS)
    async def test_byzantine_gossip_passes_all_three(self, tmp_path: Path, seed: int) -> None:
        trace = tmp_path / f"eclipse_byz_{seed}.jsonl"
        plugins = await _run("gossip_eclipse.yaml", "byzantine_gossip", trace, seed)
        verdicts = await _validator_verdicts(plugins)
        assert verdicts == {"forged": True, "equivocation": True, "eclipse": True}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("seed", _SEEDS)
    async def test_reference_gossip_fails_eclipse_check(self, tmp_path: Path, seed: int) -> None:
        trace = tmp_path / f"eclipse_ref_{seed}.jsonl"
        plugins = await _run("gossip_eclipse.yaml", "gossip", trace, seed)
        verdicts = await _validator_verdicts(plugins)
        assert verdicts["eclipse"] is False


# ---------------------------------------------------------------------------
# Determinism: same seed -> byte-identical trace, across all three scenarios
# ---------------------------------------------------------------------------


class TestDeterminism:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "yaml_name",
        ["gossip_byzantine_forgery.yaml", "gossip_signed_equivocation.yaml", "gossip_eclipse.yaml"],
    )
    @pytest.mark.parametrize("registry_plugin", ["gossip", "byzantine_gossip"])
    async def test_same_seed_identical_trace(
        self, tmp_path: Path, yaml_name: str, registry_plugin: str
    ) -> None:
        t1 = tmp_path / "run1.jsonl"
        t2 = tmp_path / "run2.jsonl"
        await ScenarioRunner(_config(yaml_name, registry_plugin, t1, 42)).run()
        await ScenarioRunner(_config(yaml_name, registry_plugin, t2, 42)).run()
        h1 = hashlib.sha256(t1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(t2.read_bytes()).hexdigest()
        assert h1 == h2
