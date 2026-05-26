# Coordination layer

**What it does.** Group decisions: propose a task, collect bids/votes,
resolve, commit.

## Interface

```python
class Coordination(Protocol):
    async def propose(self, task: Task) -> Round: ...
    async def participate(self, round: Round) -> Vote | Bid: ...
    async def resolve(self, round: Round) -> Outcome: ...
    async def commit(self, outcome: Outcome) -> None: ...
```

Full definition: [`nest_core/layers/coordination.py`](../../packages/nest-core/nest_core/layers/coordination.py).

## Built-in plugins

`contract_net` *(default)* — minimal FIPA Contract Net Protocol scaffold:
propose → bid → resolve → commit. Selects the **lowest** bid (cost
minimization) and is useful as a testing stub.

Source: [`nest_plugins_reference/coordination/contract_net.py`](../../packages/nest-plugins-reference/nest_plugins_reference/coordination/contract_net.py).

`sealed_bid` — sealed-bid auction with two configurable mechanisms:

* `vickrey` *(default)* — second-price sealed-bid; truthful bidding is
  a weakly dominant strategy under standard assumptions.
* `first_price` — first-price sealed-bid.

Both variants support an optional reserve price, deterministic
tie-breaking (lex-min bidder id), and FIPA-style round state
(`open → resolved → committed`) so out-of-order operations raise.
The companion module
[`coordination/validators.py`](../../packages/nest-plugins-reference/nest_plugins_reference/coordination/validators.py)
exposes mechanism-design property checks (allocative efficiency,
winner IR, seller reserve, Vickrey payment correctness, single winner).

Source: [`nest_plugins_reference/coordination/sealed_bid.py`](../../packages/nest-plugins-reference/nest_plugins_reference/coordination/sealed_bid.py).

Pick a mechanism per-scenario:

```yaml
layers:
  coordination: sealed_bid
```

Scenarios that exercise this layer: `auction`, `voting`, `consensus`.
The `consensus` validator checks quorum (default 2/3); it is not full
BFT — that's a great thing to plug your own implementation into.

## Writing your own

See [`writing-a-plugin.md`](../writing-a-plugin.md). Register under
entry point group `nest.plugins.coordination`.

Good fits to test here: Raft, Paxos, BFT variants (Tendermint, HotStuff,
PBFT), gossip-based aggregation.
