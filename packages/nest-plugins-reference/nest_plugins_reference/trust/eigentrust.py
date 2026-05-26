# SPDX-License-Identifier: Apache-2.0
"""EigenTrust plugin — transitive, Sybil-resistant reputation.

Implements the EigenTrust algorithm of Kamvar, Schlosser, and Garcia-Molina
(WWW '03, "The EigenTrust Algorithm for Reputation Management in P2P
Networks"). Global trust is computed as the principal left eigenvector of
the row-stochastic local-trust matrix, with a teleport to a "pre-trusted"
distribution that protects against Sybil attacks.

Why this matters
----------------
The default ``score_average`` trust plugin treats every report as equally
credible and ignores who reported it. A malicious clique can therefore
inflate (or trash) any agent's score by spamming reports. EigenTrust fixes
this in two ways:

1. Reports are weighted by the *reporter's* current trust — an agent you
   already distrust cannot lower someone else's score.
2. A small teleport probability ``a`` to a fixed set of pre-trusted seeds
   bounds the influence of any Sybil cluster regardless of size.

The implementation is deterministic given the same evidence sequence
(stable agent ordering, fixed power-iteration tolerance and cap), so it
preserves NEST's "same seed -> same trace" guarantee.

Example::

    trust = EigenTrust(pre_trusted={AgentId("observer-0")})
    await trust.report(agent_id, Evidence(reporter=..., subject=..., kind="positive"))
    score = await trust.score(AgentId("a1"))

References
----------
- Kamvar, Schlosser, Garcia-Molina. "The EigenTrust Algorithm for
  Reputation Management in P2P Networks." WWW 2003.
- Page, Brin, Motwani, Winograd. "The PageRank Citation Ranking" (1998).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from nest_core.types import (
    AgentId,
    Attestation,
    Claim,
    Evidence,
    ReputationScore,
    Signature,
)

# Reasonable defaults from the EigenTrust paper. ``alpha`` (teleport
# probability) of 0.1-0.2 is standard; we pick 0.15 (the PageRank default)
# so the seed mass is small but non-negligible. Power iteration converges
# geometrically with rate ``1 - alpha`` so 64 iterations is plenty for any
# practical agent count and the tolerance below is the real stopping rule.
_DEFAULT_ALPHA = 0.15
_DEFAULT_MAX_ITERATIONS = 64
_DEFAULT_TOLERANCE = 1e-8


class EigenTrust:
    """Transitive, Sybil-resistant trust via the EigenTrust algorithm.

    The class maintains a sparse local-trust matrix ``C[i][j]`` =
    normalized positive feedback that reporter ``i`` has provided about
    subject ``j``. Calling :meth:`score` runs power iteration on a
    teleport-smoothed version of ``C`` and returns the global trust
    value for ``agent``.

    The matrix is recomputed lazily: ``report`` invalidates the cached
    eigenvector, ``score`` recomputes it on the next call. For workloads
    with many ``score`` queries between ``report`` calls this gives a
    flat amortized cost.

    Parameters
    ----------
    identity:
        Optional NEST identity plugin used to sign attestations. The
        reference :class:`ScoreAverageTrust` accepts it; we mirror the
        signature for drop-in compatibility.
    pre_trusted:
        Iterable of agent ids that form the seed set ``p``. If empty
        (the default), ``p`` is the uniform distribution over agents
        that have ever appeared as a reporter or a subject.
    alpha:
        Teleport probability (the weight of ``p``). Higher values give
        stronger Sybil resistance at the cost of less responsiveness to
        peer evidence. Defaults to 0.15.
    max_iterations / tolerance:
        Power-iteration stopping rule. The defaults are tight enough
        that scores agree to ~7 significant figures across runs.

    Example::

        trust = EigenTrust(pre_trusted={AgentId("observer-0")}, alpha=0.15)
        await trust.report(target, Evidence(reporter=r, subject=target, kind="positive"))
        rep = await trust.score(target)
    """

    def __init__(
        self,
        identity: Any = None,
        *,
        pre_trusted: Iterable[AgentId] | None = None,
        alpha: float = _DEFAULT_ALPHA,
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
        tolerance: float = _DEFAULT_TOLERANCE,
    ) -> None:
        if not 0.0 < alpha < 1.0:
            msg = f"alpha must be in (0, 1), got {alpha}"
            raise ValueError(msg)
        if max_iterations < 1:
            msg = f"max_iterations must be >= 1, got {max_iterations}"
            raise ValueError(msg)
        if tolerance <= 0:
            msg = f"tolerance must be > 0, got {tolerance}"
            raise ValueError(msg)

        self._identity = identity
        self._alpha = alpha
        self._max_iterations = max_iterations
        self._tolerance = tolerance
        self._pre_trusted: set[AgentId] = set(pre_trusted or [])

        # Sparse local trust: positive[reporter][subject], negative[r][s].
        # We keep them separate so an agent with mixed feedback gets a
        # net-positive credit rather than being silently averaged out.
        self._positive: dict[AgentId, dict[AgentId, int]] = {}
        self._negative: dict[AgentId, dict[AgentId, int]] = {}
        self._stakes: dict[AgentId, int] = {}
        self._sample_count: dict[AgentId, int] = {}
        self._agents: set[AgentId] = set()
        self._dirty = True
        self._global_trust: dict[AgentId, float] = {}
        self._iterations_last_run = 0  # exposed for tests / metrics

    # ---------------------------------------------------------------- API

    async def score(self, agent: AgentId) -> ReputationScore:
        """Return the global EigenTrust score for ``agent`` in [0, 1].

        Recomputes the eigenvector if any reports have arrived since the
        last call. Returns the neutral prior (0.5) for unknown agents,
        matching :class:`ScoreAverageTrust`'s behaviour so swapping
        plugins doesn't change baseline numbers.

        Example::

            rep = await trust.score(AgentId("a1"))
        """
        if not self._agents:
            return ReputationScore(agent_id=agent, score=0.5, confidence=0.0, sample_count=0)

        if self._dirty:
            self._recompute()

        raw = self._global_trust.get(agent)
        if raw is None:
            # Agent we've never heard of: same neutral prior as the
            # reference plugin so validators that compare baselines
            # don't see a free win.
            return ReputationScore(agent_id=agent, score=0.5, confidence=0.0, sample_count=0)

        # Normalise so the most-trusted agent gets ~1.0 (raw eigenvector
        # entries sum to 1, which makes them hard to compare to the
        # reference plugin's [0, 1] scale).
        max_val = max(self._global_trust.values()) or 1.0
        score = raw / max_val

        samples = self._sample_count.get(agent, 0)
        confidence = min(1.0, samples / 100.0)
        return ReputationScore(
            agent_id=agent,
            score=score,
            confidence=confidence,
            sample_count=samples,
        )

    async def attest(self, agent: AgentId, claim: Claim) -> Attestation:
        """Create a (possibly signed) attestation about ``agent``.

        Mirrors :class:`ScoreAverageTrust.attest`: if an identity plugin
        is configured we use it to sign, otherwise we return a stub
        signature so callers can still inspect the structure.

        Example::

            att = await trust.attest(AgentId("a1"), claim)
        """
        sig = Signature(signer=AgentId("system"), value=b"attestation", algorithm="none")
        if self._identity is not None:
            sig = self._identity.sign(claim.model_dump_json().encode())
        return Attestation(issuer=AgentId("system"), claim=claim, signature=sig)

    async def report(self, agent: AgentId, evidence: Evidence) -> None:
        """Record ``evidence`` against ``agent``'s reputation.

        ``evidence.reporter`` is the source of the report. Unlike
        :class:`ScoreAverageTrust`, EigenTrust *does* care who reported:
        a report from an agent with no incoming trust contributes
        approximately nothing to the global score.

        Recognised evidence kinds:

        - ``"positive"``: +1 to the (reporter, subject) edge.
        - ``"negative"`` / ``"byzantine"``: +1 to the negative-edge count.
        - Anything else: counted as a sample but does not move the edges
          (useful for "I observed but make no claim" telemetry).

        Example::

            ev = Evidence(reporter=AgentId("a2"), subject=AgentId("a1"), kind="positive")
            await trust.report(AgentId("a1"), ev)
        """
        # The reference plugin keys by the ``agent`` argument and ignores
        # ``evidence.subject``. We prefer ``evidence.subject`` when set so
        # callers can pass either, but fall back to ``agent`` for parity.
        subject = evidence.subject or agent
        reporter = evidence.reporter

        self._agents.add(subject)
        self._agents.add(reporter)
        self._sample_count[subject] = self._sample_count.get(subject, 0) + 1

        if evidence.kind == "positive":
            self._positive.setdefault(reporter, {})
            self._positive[reporter][subject] = self._positive[reporter].get(subject, 0) + 1
        elif evidence.kind in ("negative", "byzantine"):
            self._negative.setdefault(reporter, {})
            self._negative[reporter][subject] = self._negative[reporter].get(subject, 0) + 1
        # ``unknown`` kinds: counted but neutral.
        self._dirty = True

    async def stake(self, agent: AgentId, amount: int) -> None:
        """Stake reputation on ``agent``'s good behaviour.

        Kept for interface compatibility; staking does not influence
        the EigenTrust eigenvector in this implementation, but the
        amount is tracked so callers / validators can inspect it.

        Example::

            await trust.stake(AgentId("a1"), 100)
        """
        self._stakes[agent] = self._stakes.get(agent, 0) + amount

    # ------------------------------------------------------- introspection

    def global_trust(self) -> dict[AgentId, float]:
        """Return the raw (sums-to-1) global trust vector. For tests / metrics.

        Example::

            t = trust.global_trust()  # dict[AgentId, float]
        """
        if self._dirty:
            self._recompute()
        return dict(self._global_trust)

    @property
    def iterations_last_run(self) -> int:
        """Number of power-iteration steps in the most recent recompute."""
        return self._iterations_last_run

    # --------------------------------------------------------- internals

    def _local_trust_row(self, reporter: AgentId) -> dict[AgentId, float]:
        """Compute the row-stochastic local trust ``s_ij = max(p_ij - n_ij, 0)``.

        Following the paper (eq. 1 / 2): normalise the non-negative
        residual by its row sum. Reporters with no net-positive feedback
        return an empty dict; the matrix builder then re-distributes
        their mass to the pre-trusted set (the paper's "well-defined C"
        construction).
        """
        pos = self._positive.get(reporter, {})
        neg = self._negative.get(reporter, {})
        residuals: dict[AgentId, float] = {}
        total = 0.0
        for subject, p in pos.items():
            n = neg.get(subject, 0)
            r = max(p - n, 0)
            if r > 0:
                residuals[subject] = float(r)
                total += float(r)
        if total <= 0:
            return {}
        return {s: v / total for s, v in residuals.items()}

    def _seed_vector(self, ordered_agents: list[AgentId]) -> dict[AgentId, float]:
        """Build the teleport / seed distribution ``p``.

        Defaults to uniform over all known agents when no explicit seed
        set was provided — that matches the simplest variant in the
        paper. With an explicit seed set, mass is split uniformly across
        seeds that we've actually observed; unknown seeds are ignored so
        a stale config can't shift trust onto absent agents.
        """
        if not ordered_agents:
            return {}
        if not self._pre_trusted:
            w = 1.0 / len(ordered_agents)
            return {a: w for a in ordered_agents}
        active_seeds = [a for a in ordered_agents if a in self._pre_trusted]
        if not active_seeds:
            # Configured seeds haven't shown up yet -> uniform fallback.
            w = 1.0 / len(ordered_agents)
            return {a: w for a in ordered_agents}
        w = 1.0 / len(active_seeds)
        return {a: w for a in active_seeds}

    def _recompute(self) -> None:
        """Power-iterate the EigenTrust update until convergence.

        We use a dict-of-dicts representation rather than a dense matrix
        so the cost scales with the number of *edges* (reports), not
        n^2. Convergence is geometric with rate ``1 - alpha``; in
        practice 5-15 iterations are plenty for ``alpha = 0.15``.
        """
        ordered = sorted(self._agents)  # stable order -> deterministic
        if not ordered:
            self._global_trust = {}
            self._dirty = False
            self._iterations_last_run = 0
            return

        seed = self._seed_vector(ordered)

        # Precompute the (sparse) C^T rows: for each subject ``j``, the
        # list of (reporter ``i``, weight ``c_ij``) pairs.
        transposed: dict[AgentId, list[tuple[AgentId, float]]] = {a: [] for a in ordered}
        sinks: list[AgentId] = []  # reporters with no usable local trust
        for reporter in ordered:
            row = self._local_trust_row(reporter)
            if not row:
                sinks.append(reporter)
                continue
            for subject, w in row.items():
                transposed.setdefault(subject, []).append((reporter, w))

        # Initialise with the seed distribution (the paper's choice;
        # any positive vector summing to 1 works, but starting at the
        # seed shaves a couple of iterations off convergence).
        t = dict(seed)

        alpha = self._alpha
        last_delta = float("inf")
        iterations = 0
        for step in range(1, self._max_iterations + 1):
            iterations = step
            # Dangling mass: reporters with no outgoing local trust
            # redistribute according to the seed vector (standard
            # PageRank treatment of sinks).
            dangling = sum(t.get(a, 0.0) for a in sinks)
            t_next: dict[AgentId, float] = {}
            for subject in ordered:
                propagated = 0.0
                for reporter, w in transposed.get(subject, ()):
                    propagated += w * t.get(reporter, 0.0)
                # Spread sink mass uniformly through ``seed`` (this is
                # the standard reformulation that keeps C row-stochastic).
                propagated += dangling * seed.get(subject, 0.0)
                t_next[subject] = (1.0 - alpha) * propagated + alpha * seed.get(subject, 0.0)

            # L1 normalisation guards against floating-point drift; in
            # exact arithmetic the vector already sums to 1.
            total = sum(t_next.values())
            if total > 0:
                t_next = {k: v / total for k, v in t_next.items()}

            last_delta = sum(abs(t_next.get(a, 0.0) - t.get(a, 0.0)) for a in ordered)
            t = t_next
            if last_delta < self._tolerance:
                break

        self._global_trust = t
        self._dirty = False
        self._iterations_last_run = iterations
