# feat(registry): byzantine-resistant gossip -- signed cards, signed-equivocation quarantine, eclipse-resistant sampling

**Persona for this review: trust/honesty auditor.** I built the adversarial
validators *before* trusting my own plugin's guarantees, and I am reporting
every limitation I found while building it, not just the attacks it catches.
If you are reviewing this for a security-sensitive merge, read
[`VERIFICATION.md`](nest_plugins_reference/registry/VERIFICATION.md) in
full, not just this summary.

## Headline: a validly-signed equivocator still poisons the network

The other prior art in this space (`#67`, registration-only card signing)
answers "did the claimed publisher actually sign this card?" -- necessary,
but not sufficient. It does not answer, and *cannot* answer by construction:
"did this publisher sign **two different, individually valid** cards at the
same version?" Both cards pass every check a registration-time signature can
run, in isolation. `#67` would accept either one without complaint. The only
way to catch it is to compare a publisher's writes to each other, not to
verify a signature against itself -- that is the invariant this PR adds
(`scenarios/gossip_signed_equivocation.yaml`, the novelty proof scenario).

This defense is **mesh-wide, not topology-bounded**: even an equivocator that
never sends its two conflicting cards to any common recipient -- delivering
card1 only to one group of peers and card2 only to a disjoint group, so no
single node ever directly witnesses both -- is still caught at **every**
honest node. Getting this genuinely mesh-wide took two rounds of work, and
the honest story is in [`VERIFICATION.md`](nest_plugins_reference/registry/VERIFICATION.md#honest-limitations-every-one-gathered-across-the-build)
(limitation 4). A first fix carried a per-entry **content hash** in the
`OP_DIGEST` payload so `_compute_missing` hands over a
same-version-but-different-content entry rather than treating the peer as "in
sync" -- enough for N=2 / a single equivocator
(`test_disjoint_delivery_equivocation_is_caught`). But that is **not
sufficient** at N>2 honest nodes with multiple equivocators: the instant a
node witnesses the conflict it evicts the card, dropping it from its digest,
so it stops relaying the conflicting copy -- "eviction halts relay" -- and a
node that only ever saw one side, whose neighbors holding the other side all
evict first, strands permanently (reproduced at N=10 / five equivocators,
`test_disjoint_multi_equivocator_no_stranding`). The real fix gossips the
equivocation **proof** -- the two conflicting, individually-signature-valid
writes for `(E, v)` -- independently of card eviction: the proof survives
eviction (`self._equivocation_proofs`), rides anti-entropy as its own
`OP_EQPROOF` wire item advertised via a known-byzantine digest section, and
is **independently re-verified on receipt** (both signatures + same-`(E,
v)`-different-hash, `_verify_proof`/`_ingest_proof`) so a relay cannot forge
one to frame an honest publisher. A stranded node therefore learns `E` is
byzantine from any honest neighbor, and every honest node converges on
quarantining and evicting `E` regardless of delivery topology
(`test_disjoint_multi_equivocator_no_stranding`,
`test_fabricated_equivocation_proof_does_not_frame_honest_publisher`). The
one residual honest condition: the honest sub-network must be connected (not
partitioned) for the proof to reach everyone, and convergence is eventual
(a transient in-flight window), never instantaneous.

## Threat model

`gossip` (`#24`, merged) gives eventually-consistent discovery under
honest-but-partitioned failures: every agent gossips its local view, and the
simulator's partition logic naturally blocks cross-partition propagation.
It assumes every participant plays by the rules. This PR removes that
assumption on three specific, named fronts:

| # | Attack | `gossip`'s exposure | This plugin's defense |
|---|---|---|---|
| 1 | Forged/impersonated cards **in gossip propagation** (not just at registration) | Merges any card on sight -- no signing, no verification, anywhere | Signs `(content, version, tombstone)` at write time; re-verifies on **every** `OP_PUSH` hop before merge, dropping unsigned/impersonating/forged/replayed-under-a-forged-tag cards (`rejections` ledger, reason-coded) |
| 2 | **Signed equivocation** -- a publisher validly signs two different cards at the same version, possibly delivered to disjoint peer groups with no common recipient | Last-writer-wins keeps whichever conflicting card arrives first at each node, silently and permanently, no ledger anywhere | Witness map over `(publisher, version)` -> content hash; a second, verified, content-differing write proves the publisher is byzantine, quarantines it permanently, evicts it from the view, records `(publisher, version)` in `equivocations`. The self-verifying **proof** (the two conflicting signed writes) is then gossiped as its own `OP_EQPROOF` item, surviving card eviction and re-verified on receipt, so detection reaches **every** honest node under disjoint multi-equivocator delivery -- not just the direct witnesses, and not defeated by eviction-halts-relay stranding |
| 3 | **Eclipse** -- an honest agent fed only byzantine/rejected data | Pure-uniform peer sampling every round, no memory -- a large-enough byzantine fraction or unlucky draw can exclude a victim's only honest peer indefinitely | Every round draws a deterministic **anchor set** (lexicographically-first half of peers by `AgentId`) plus a seeded-random remainder, so one fixed, stable contact is retried every round instead of only when the dice land right |

## Calibrated claim -- read this before merging

**Byzantine-resistant and attack-detecting, for these three named attacks,
up to a bounded byzantine fraction, under the topologies actually
exercised.** This is explicitly **not BFT** (no consensus, no quorum, no
`f < n/3` proof) and **not unconditionally secure**. In particular:

- **Eclipse resistance is heuristic (an anchor set), not a proof.** The
  anchor half is positional (lexicographically-first `AgentId`s among a
  victim's current peers), not identity-vetted. An adversary that controls
  every anchor slot for a specific victim defeats the guarantee for that
  victim entirely, and there is no rotation mechanism if an anchor slot
  itself turns out to be byzantine. The eclipse scenario's gossip-FAIL is
  **empirically tuned to seeds 42/7/1337** (found by direct simulation,
  not a closed-form bound) -- a seed outside that set is not guaranteed to
  reproduce it.
- **`InertByzantineDriverAgent` (the eclipse scenario's adversary) models
  Sybil dilution by silence, not an active-lying byzantine agent.** It
  never registers, gossips, or answers. A byzantine agent that actively
  lies about its digest is a stronger, different attack, out of scope for
  the three scenarios shipped here.
- **Quarantine is permanent, by design, with no rehabilitation path.** A
  publisher caught equivocating once has every later card refused forever
  on this registry instance -- including a genuinely honest one signed
  after the fact. No re-trust mechanism exists; a real deployment wanting
  one would need to build it externally.
- **The equivocation *proof* is gossiped; a "who-quarantined-whom" opinion
  is not.** What propagates mesh-wide is the self-verifying proof (the two
  conflicting signed writes), which every node re-verifies independently
  before acting -- not a node's unverifiable assertion "I quarantined E,"
  which would be a framing vector. Convergence is therefore **eventual, not
  instantaneous**: while a proof is still in flight there is a transient
  window during which some honest nodes have quarantined the equivocator and
  others have not yet received the proof. That window closes as propagation
  completes, and convergence to "quarantined and evicted everywhere" then
  holds mesh-wide even under disjoint multi-equivocator delivery -- **as long
  as the honest sub-network is connected** (a partition, or a full eclipse of
  a victim, delays the proof until it heals, exactly like any other gossip
  data). This is the one residual honest caveat on the mesh-wide claim; see
  the disjoint-delivery fix above and `VERIFICATION.md` limitation 4.
- **Validators are trace/snapshot-evidence-bounded**, like every NANDA Town
  validator -- they judge the evidence supplied to them (view snapshots,
  cards, ledgers), not run ground truth. `check_no_forged_card_in_view`
  treats "cannot be checked" as a FAIL rather than a silent pass for
  exactly this reason.
- A quarantine reason-code precision nit: a forged card arriving under an
  *already*-quarantined publisher id is logged as `quarantined`, not
  `bad_signature` (quarantine short-circuits before verification runs) --
  harmless, the card is rejected either way, only the reason code is
  imprecise in that one case.

Full list, with the reasoning behind each one: [`VERIFICATION.md`](nest_plugins_reference/registry/VERIFICATION.md#honest-limitations-every-one-gathered-across-the-build).

## FAIL/PASS matrix

Rows = the 3 mandated validators
([`registry_byzantine_validators.py`](nest_plugins_reference/validators/registry_byzantine_validators.py)).
Columns = `{in_memory, gossip, byzantine_gossip}` x `{forgery,
signed_equivocation, eclipse}`. Captured from an actual scenario run at seed
42, cross-checked against the full 30-test gate at seeds 7 and 1337 (all
identical).

| Validator                          | in_memory (all 3) | gossip / forgery | gossip / equivocation | gossip / eclipse | byzantine_gossip / forgery | byzantine_gossip / equivocation | byzantine_gossip / eclipse |
|-------------------------------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `check_no_forged_card_in_view`      | N/A | **FAIL** | **FAIL**\* | **FAIL**\* | PASS | PASS | PASS |
| `check_no_equivocation_accepted`    | N/A | PASS | **FAIL** | PASS | PASS | PASS | PASS |
| `check_no_eclipse`                  | N/A | PASS | PASS | **FAIL** | PASS | PASS | PASS |

\* Structural, not attack-specific in those two scenarios -- `gossip` never
signs anything at all, including honest agents' own registrations. The
attack-specific proof (do the forger's phantom ids actually land in / get
rejected from honest views) is asserted directly by
`test_reference_gossip_accepts_phantom_cards` /
`test_byzantine_gossip_rejects_phantom_cards`, not by this validator's
verdict alone.

`in_memory` is marked **N/A, not PASS**: it cannot be substituted into any
of these scenarios at all (`TypeError: InMemoryRegistry.__init__() takes 1
positional argument but 3 were given` -- it is a single globally-shared
dict with no per-agent view, no gossip mechanics, no equivocation ledger).
The three validators are written against the distributed-view model
`gossip`/`byzantine_gossip` share; `in_memory` has no comparable
adversarial surface to run them against. See `VERIFICATION.md` for the full
argument -- this is not a loophole, `in_memory` genuinely has no attack
surface these validators are testing for, and no defense against it either.

### Reproduce it

```bash
uv run pytest packages/nest-plugins-reference/tests/test_byzantine_gossip_scenario.py -v
uv run pytest packages/nest-plugins-reference/tests/test_registry_byzantine_validators.py -v
```

See `VERIFICATION.md` for the exact `uv run python` snippet that prints the
literal verdict dict per scenario/plugin pair.

## What's in this PR

- `nest_plugins_reference/registry/byzantine_gossip.py` --
  `ByzantineGossipRegistry` (signed cards, forged/impersonation rejection,
  signed-equivocation detection + permanent quarantine, eclipse-resistant
  anchor+random peer sampling). Registered in `nest_core.plugins._BUILTINS`
  and `packages/nest-plugins-reference/pyproject.toml`'s
  `nest.plugins.registry` entry points.
- `nest_plugins_reference/validators/registry_byzantine_validators.py` --
  `check_no_forged_card_in_view`, `check_no_equivocation_accepted`,
  `check_no_eclipse`.
- `scenarios/gossip_byzantine_forgery.yaml`,
  `scenarios/gossip_signed_equivocation.yaml`,
  `scenarios/gossip_eclipse.yaml` -- deterministic under seeds 42, 7, 1337.
- Tests: `test_byzantine_gossip.py` (unit), `test_byzantine_gossip_properties.py`
  (30 Hypothesis property tests + fraction sweep + edge cases),
  `test_registry_byzantine_validators.py` (validator unit tests),
  `test_byzantine_gossip_scenario.py` (30-test end-to-end FAIL/PASS gate +
  determinism).
- `docs/layers/registry.md` -- byzantine_gossip subsection.
- `nest_plugins_reference/registry/VERIFICATION.md` -- full evidence +
  every honest limitation.

## CI

`make ci-local` -- all five checks green (`uv sync`, `ruff check`, `ruff
format --check`, `pyright`, `pytest -v`).

## Branch status

`hackathon/bogacsmz-registry-byzantine-gossip`. **No PR opened** -- handing
the branch back for review with this draft, the matrix, and
`VERIFICATION.md`.
