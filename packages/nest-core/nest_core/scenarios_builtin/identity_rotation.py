# SPDX-License-Identifier: Apache-2.0
"""Identity key-rotation scenario with byzantine forgery/backdating attackers.

Honest agents sign heartbeat messages with whatever identity plugin the YAML
configures (``identity: ed25519_rotating`` for the real run), rotate that key
once mid-run, and keep signing under the new key. Byzantine agents
(``failures.byzantine_agents`` fraction, default 10%) attempt the two attacks
the rotating plugin is built to defeat:

* **post-rotation forgery** — forge a fresh signature with their *own* stale,
  rotated-out key after rotation, and
* **backdating** — sign with the *new* key but claim the signature belongs in
  the old key's window.

The agents resolve their signing identity from ``ctx.plugins["identity"]`` (the
configured plugin), not a hardcoded class. Rotation and stale-key signing are
*capability-gated* via ``hasattr`` — so running the scenario with
``identity: did_key`` does **not** crash; it simply emits no ``rotate:`` lines
and signatures with an empty ``key_id``. The ``identity_rotation`` validator
then fails (no rotation, honest signatures resolve to no window), which is the
honest demonstration that ``did_key`` cannot do historical verification. The
same scenario under ``ed25519_rotating`` passes.

Every signing/rotation event is emitted into the trace in a line protocol the
``identity_rotation`` validator parses (see
``nest_core.validators.validate_identity_rotation_signatures``). The validator
anchors every as-of check to the trace's externally observed ``ts`` — never to
the attacker-controlled claimed tick alone — so both attacks are caught.

Trace line protocol (carried in message bodies, ``:``-delimited):

* ``rotate:<agent>:<old_key_id>:<new_key_id>:<rotate_tick>`` — a rotation; the
  old key's window closes at ``rotate_tick`` and the new key's window opens.
* ``signed:<agent>:<key_id>:<claimed_tick>:<verdict>`` — a signed heartbeat;
  ``verdict`` is ``ok`` (honest), ``forge`` (post-rotation forgery), or
  ``backdate`` (claimed tick moved into a closed window).

Example::

    agents = identity_rotation_factory(config, plugins)
"""

from __future__ import annotations

from typing import Any

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId


def _identity_of(ctx: AgentContext) -> Any:
    """Return the per-agent identity instance from the agent's context.

    Example::

        ident = _identity_of(ctx)
    """
    return ctx.plugins.get("identity")


def _key_id_token(sig: Any) -> str:
    """Render a signature's ``key_id`` for the trace (``None`` for keyless plugins).

    Example::

        token = _key_id_token(sig)
    """
    return str(getattr(sig, "key_id", None))


def _signed_at_token(sig: Any, fallback: float) -> str:
    """Render a signature's claimed ``signed_at`` tick, falling back when absent.

    Example::

        token = _signed_at_token(sig, ctx.time)
    """
    value = getattr(sig, "signed_at", None)
    return str(fallback if value is None else value)


class HonestSigner(StateMachineAgent):
    """Signs heartbeats, rotates its key once mid-run, keeps signing.

    Emits ``rotate:`` and ``signed:...:ok`` lines so the validator can rebuild
    key windows and confirm every honest signature sits inside a valid window.
    Rotation is capability-gated: if the configured identity plugin has no
    ``rotate_key`` (e.g. ``did_key``), the agent skips rotation and keeps
    signing — the trace still records the (keyless) signatures.

    Example::

        agent = HonestSigner(AgentId("signer-0"), AgentId("auditor-0"), rounds=6)
    """

    def __init__(
        self,
        agent_id: AgentId,
        auditor: AgentId,
        rounds: int = 6,
        rotate_at_round: int = 3,
    ) -> None:
        self._id = agent_id
        self._auditor = auditor
        self._rounds = rounds
        self._rotate_at_round = rotate_at_round
        self._round = 0

    async def _emit_round(self, ctx: AgentContext) -> None:
        self._round += 1
        ident = _identity_of(ctx)
        if ident is None:  # pragma: no cover - scenario always configures identity
            return
        if hasattr(ident, "set_clock"):
            ident.set_clock(ctx.time)

        if self._round == self._rotate_at_round and hasattr(ident, "rotate_key"):
            rec = ident.rotate_key(b"rot:" + str(self._id).encode())
            await ctx.send(
                self._auditor,
                f"rotate:{self._id}:{rec.old_key_id}:{rec.new_key_id}:{ctx.time}".encode(),
            )

        sig = ident.sign(f"heartbeat:{self._id}:{self._round}".encode())
        await ctx.send(
            self._auditor,
            f"signed:{self._id}:{_key_id_token(sig)}:{_signed_at_token(sig, ctx.time)}:ok".encode(),
        )

    async def on_start(self, ctx: AgentContext) -> None:
        """Emit the first signing round.

        Example::

            await agent.on_start(ctx)
        """
        await self._emit_round(ctx)

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """Advance one round on each auditor ``tick:`` pulse.

        Example::

            await agent.on_message(ctx, auditor, b"tick:1")
        """
        msg = payload.decode("utf-8", errors="replace")
        if msg.startswith("tick:") and self._round < self._rounds:
            await self._emit_round(ctx)


class ByzantineSigner(StateMachineAgent):
    """Rotates, then attempts post-rotation forgery and backdating.

    The attacker holds its *own* old key (the realistic "key was compromised"
    threat) and tries both attacks. Each attack is emitted with the **true**
    observed tick as the trace ``ts`` but a falsified claimed tick / stale
    ``key_id`` — exactly the data the validator uses to reject it. Attacks are
    capability-gated: against a plugin with no ``rotate_key``/``sign_with`` the
    attacker has nothing to forge with and behaves like an honest signer.

    Example::

        agent = ByzantineSigner(AgentId("byz-0"), AgentId("auditor-0"), rounds=6)
    """

    def __init__(
        self,
        agent_id: AgentId,
        auditor: AgentId,
        rounds: int = 6,
        rotate_at_round: int = 3,
    ) -> None:
        self._id = agent_id
        self._auditor = auditor
        self._rounds = rounds
        self._rotate_at_round = rotate_at_round
        self._round = 0
        self._old_key_id = ""

    async def _emit_round(self, ctx: AgentContext) -> None:
        self._round += 1
        ident = _identity_of(ctx)
        if ident is None:  # pragma: no cover - scenario always configures identity
            return
        if hasattr(ident, "set_clock"):
            ident.set_clock(ctx.time)

        can_attack = hasattr(ident, "rotate_key") and hasattr(ident, "sign_with")

        if self._round == self._rotate_at_round and can_attack:
            self._old_key_id = str(ident.current_key_id)
            rec = ident.rotate_key(b"rot:" + str(self._id).encode())
            await ctx.send(
                self._auditor,
                f"rotate:{self._id}:{rec.old_key_id}:{rec.new_key_id}:{ctx.time}".encode(),
            )

        if self._round <= self._rotate_at_round or not can_attack:
            # Behave honestly until the key has rotated out (or when the plugin
            # has no rotation to abuse).
            sig = ident.sign(f"heartbeat:{self._id}:{self._round}".encode())
            await ctx.send(
                self._auditor,
                (
                    f"signed:{self._id}:{_key_id_token(sig)}:{_signed_at_token(sig, ctx.time)}:ok"
                ).encode(),
            )
            return

        # Attack A: post-rotation forgery with the stale, rotated-out key.
        from nest_plugins_reference.identity.ed25519_rotating import KeyId

        forged = ident.sign_with(
            f"forged:{self._id}:{self._round}".encode(), KeyId(self._old_key_id)
        )
        await ctx.send(
            self._auditor,
            (
                f"signed:{self._id}:{_key_id_token(forged)}:"
                f"{_signed_at_token(forged, ctx.time)}:forge"
            ).encode(),
        )

        # Attack B: backdating — sign with the new key but claim an old tick.
        sig = ident.sign(f"backdated:{self._id}:{self._round}".encode())
        backdated_tick = 0.0  # claim it sits at the very start (old key's window)
        await ctx.send(
            self._auditor,
            f"signed:{self._id}:{_key_id_token(sig)}:{backdated_tick}:backdate".encode(),
        )

    async def on_start(self, ctx: AgentContext) -> None:
        """Emit the first signing round.

        Example::

            await agent.on_start(ctx)
        """
        await self._emit_round(ctx)

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """Advance one round on each auditor ``tick:`` pulse.

        Example::

            await agent.on_message(ctx, auditor, b"tick:1")
        """
        msg = payload.decode("utf-8", errors="replace")
        if msg.startswith("tick:") and self._round < self._rounds:
            await self._emit_round(ctx)


class AuditorAgent(StateMachineAgent):
    """Drives rounds and records signatures; the trace is the audit log.

    The auditor pulses every signer once per round (``tick:`` messages) so the
    simulation advances deterministically. All real verification happens
    offline in the ``identity_rotation`` validator against the emitted trace.

    Example::

        auditor = AuditorAgent(AgentId("auditor-0"), signers, rounds=6)
    """

    def __init__(self, agent_id: AgentId, signers: list[AgentId], rounds: int = 6) -> None:
        self._id = agent_id
        self._signers = signers
        self._rounds = rounds
        self._round = 1  # round 1 is each signer's own on_start at tick 0

    async def on_start(self, ctx: AgentContext) -> None:
        """Schedule the first round pulse one tick ahead so the clock advances.

        Round 1 is kicked off by each signer's own ``on_start`` at tick 0. The
        auditor schedules a self ``pulse:`` for each subsequent round at a
        strictly increasing tick, so round ``N`` lands at logical tick ``N - 1``.
        This is what makes the trace's externally observed ``ts`` advance, which
        the validator anchors its as-of checks to.

        Example::

            await auditor.on_start(ctx)
        """
        await self._schedule_next(ctx)

    async def _schedule_next(self, ctx: AgentContext) -> None:
        if self._round >= self._rounds:
            return
        await ctx.schedule(1.0, b"pulse:")

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """Drive the next round on each self-scheduled ``pulse:`` tick.

        On each pulse the auditor advances the round counter, sends a ``tick:``
        message to every signer (delivered at the now-advanced clock), and
        schedules the following pulse. Signers reply with ``signed:`` lines,
        which are recorded but do not themselves drive the schedule.

        Example::

            await auditor.on_message(ctx, auditor, b"pulse:")
        """
        msg = payload.decode("utf-8", errors="replace")
        if not msg.startswith("pulse:"):
            return
        self._round += 1
        for signer in self._signers:
            await ctx.send(signer, f"tick:{self._round}".encode())
        await self._schedule_next(ctx)


def _provision_identities(
    plugins: dict[str, Any],
    signer_ids: list[AgentId],
) -> None:
    """Instantiate one identity per signer from the configured plugin class.

    Mirrors ``marketplace_factory``'s identity wiring: resolve the class at
    ``plugins["identity"]``, build a per-agent instance with a deterministic
    seed, cross-register peers' public keys, and stash the instances under
    ``plugins["_agent_plugins"]`` for the runner to apply as per-agent
    overrides. No-op when no identity plugin is configured.

    Example::

        _provision_identities(plugins, [AgentId("signer-0"), AgentId("byz-0")])
    """
    identity_cls = plugins.get("identity")
    if identity_cls is None or not isinstance(identity_cls, type):
        return

    identities: dict[AgentId, Any] = {
        aid: identity_cls(aid, seed=b"identity-rotation:" + str(aid).encode()) for aid in signer_ids
    }
    for aid, ident in identities.items():
        for peer_id, peer_ident in identities.items():
            if peer_id != aid and hasattr(ident, "register_peer"):
                ident.register_peer(peer_id, peer_ident.public_key)

    agent_plugins: dict[AgentId, dict[str, Any]] = plugins.setdefault("_agent_plugins", {})
    for aid, ident in identities.items():
        agent_plugins.setdefault(aid, {})["identity"] = ident

    plugins.pop("identity", None)


def identity_rotation_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
) -> dict[AgentId, StateMachineAgent]:
    """Create honest + byzantine signers and one auditor.

    The byzantine fraction comes from ``failures.byzantine_agents`` (default
    0.10). Each signer rotates its key once at ``rotate_at_round``. Every signer
    is given its own identity instance built from the configured identity plugin
    class, so swapping ``identity: did_key`` in the YAML genuinely changes agent
    behaviour (no rotation, keyless signatures) and the validator can tell the
    plugins apart.

    Example::

        agents = identity_rotation_factory(config, plugins)
    """
    task_config = config.task.config
    rounds = int(task_config.get("rounds", 6))
    rotate_at_round = int(task_config.get("rotate_at_round", 3))
    byzantine_fraction = config.failures.byzantine_agents or task_config.get(
        "byzantine_fraction", 0.10
    )

    signer_count = max(1, config.agents.count - 1)
    byzantine_count = int(signer_count * byzantine_fraction)
    honest_count = signer_count - byzantine_count

    if config.agents.roles:
        for role in config.agents.roles:
            if role.name == "honest":
                honest_count = role.count
            elif role.name == "byzantine":
                byzantine_count = role.count

    auditor_id = AgentId("auditor-0")
    honest_ids = [AgentId(f"signer-{i}") for i in range(honest_count)]
    byzantine_ids = [AgentId(f"byz-{i}") for i in range(byzantine_count)]
    signers: list[AgentId] = honest_ids + byzantine_ids

    _provision_identities(plugins, signers)

    agents: dict[AgentId, StateMachineAgent] = {}
    for aid in honest_ids:
        agents[aid] = HonestSigner(
            aid, auditor=auditor_id, rounds=rounds, rotate_at_round=rotate_at_round
        )
    for aid in byzantine_ids:
        agents[aid] = ByzantineSigner(
            aid, auditor=auditor_id, rounds=rounds, rotate_at_round=rotate_at_round
        )

    agents[auditor_id] = AuditorAgent(auditor_id, signers=signers, rounds=rounds)
    return agents
