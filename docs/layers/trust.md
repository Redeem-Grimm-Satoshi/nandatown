# Trust layer

**What it does.** Maintain per-agent reputation, accept attestations
and abuse reports, optionally support stake.

## Interface

```python
class Trust(Protocol):
    async def score(self, agent: AgentId) -> ReputationScore: ...
    async def attest(self, agent: AgentId, claim: Claim) -> Attestation: ...
    async def report(self, agent: AgentId, evidence: Evidence) -> None: ...
    async def stake(self, agent: AgentId, amount: int) -> None: ...
```

Full definition: [`nest_core/layers/trust.py`](../../packages/nest-core/nest_core/layers/trust.py).

## Default plugin

`score_average` — running mean of feedback scores. No Sybil resistance,
no decay, no stake economics.

Source: [`nest_plugins_reference/trust/score_average.py`](../../packages/nest-plugins-reference/nest_plugins_reference/trust/score_average.py).

The `reputation` scenario exercises this layer — 16 honest + 4
malicious + 1 observer that samples cheat reports probabilistically.

## `bonded_trust` : a Sybil-resistant **trust root**

With `bonded_trust`, reputation influence is bounded by a *scarce, verified* resource, not identity count. Both `score_average` and the EigenTrust plugins ration influence among identities that already exist; none stops the free *minting* of them, and `did_key` mints for free. `bonded_trust` moves the Sybil anchor out of the identity layer into a metered bond — Douceur (2002) taken seriously: the resource must be scarce and verified, never self-asserted.

**Mechanism.**
- **Self-bond gate.** An identity scores the untrusted floor (`0.0`) until it *reserves* a bond through a `StakeLedger`. A broke Sybil bidding `bond:1000000` gets nothing.
- **Reporter-weighting.** Reports weigh by the reporter's bond; unbonded reporters and self-reports carry zero. Splitting a budget across K identities buys no more influence than concentrating it.

### Pluggable scarcity anchor

The scarce resource isn't baked in — `StakeLedger` (one method, `reserve(agent, amount) -> int`) makes the anchor **swappable**, so the same trust root runs on credits, CPU, consensus, or any metered quantity. This relocation is the contribution; the bond-weighting is deliberately simple.

| ledger | scarcity |
|---|---|
| `CreditBackedLedger` | payments-layer credits |
| `ProofOfWorkLedger` | sha256 PoW (`difficulty_bits`) |
| `SelfDeclaredLedger` *(default)* | none — **test only** |

Any scarce, verified quantity works — not just raw resources. A BBS+ **capability badge** (`BadgeBackedLedger`, phase-2 `captcha4agents`) or an anchored **PARC** reputation standing (`NotaryBackedLedger`) fits the same seam; both are planned, and the PR sketches how they compose.

### Quickstart

```python
from nest_plugins_reference.trust.bonded_trust import BondedTrust
from nest_plugins_reference.trust.stake_ledgers import CreditBackedLedger

trust = BondedTrust(identity, ledger=CreditBackedLedger({AgentId("a1"): 100}), min_bond=1)
```

Or in a scenario: `trust: bonded_trust`.

### The `sybil_bond` scenario

20 unbonded Sybils cross-endorse against 5 bonded honest traders. Swap `trust:`:

```
score_average → Sybils 1.0 → FAIL      bonded_trust → Sybils 0.0 → PASS
```

Three validators FAIL on the baseline, PASS on `bonded_trust`:
`sybil_bond_no_free_trust` (no unbonded Sybil above the floor) ·
`sybil_bond_honest_trusted` (honest rank strictly above Sybils) ·
`sybil_bond_attempts_rejected` (Sybils bid and were rejected — enforced, not assumed).

### Composition

- **identity** — `bonded_trust` exists *because* `did_key` mints identities for free; it doesn't harden identity, it makes free identities inert.
- **payments** — `CreditBackedLedger` draws its scarcity straight from the payments layer's balances.
- **other trust plugins** — orthogonal to graph reputation (EigenTrust): `bonded_trust` *gates* who can hold nonzero influence; a transitive-reputation algorithm can run over the bonded set.

### Boundary

Spend *real* bond, gain real influence — intended ("most at stake, most say"), bounded by spend and independent of identity count. Free Sybils get `0.0`.

**Source:** [`bonded_trust.py`](../../packages/nest-plugins-reference/nest_plugins_reference/trust/bonded_trust.py) ·
[`stake_ledgers.py`](../../packages/nest-plugins-reference/nest_plugins_reference/trust/stake_ledgers.py) ·
[`sybil_bond.yaml`](../../scenarios/sybil_bond.yaml) · `sybil_bond_*` in
[`validators.py`](../../packages/nest-core/nest_core/validators.py)

## Writing your own

See [`writing-a-plugin.md`](../writing-a-plugin.md). Register under entry point group `nest.plugins.trust`.

Good fits to test here: EigenTrust-style transitive reputation, proof-of-stake reputation, decaying scores, attestation graphs.
