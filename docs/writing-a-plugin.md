# Writing a plugin

A Nanda Town plugin implements one of the 12 layer interfaces and is
discovered by `nest run` via Python entry points.

This guide walks through a complete, end-to-end **payments** plugin.
The same flow applies to any layer — just swap `payments` for
`transport`, `identity`, etc.

## TL;DR

1. Write a class with the right method signatures (no inheritance
   required — interfaces use `typing.Protocol`).
2. Register it under `nest.plugins.<layer>` in `pyproject.toml`.
3. `pip install -e .`
4. Point a scenario at its name.

## Step 1: Pick a layer

The twelve layers are: `transport`, `comms`, `identity`, `registry`,
`auth`, `trust`, `payments`, `coordination`, `negotiation`, `memory`,
`privacy`, `datafacts`.

To see what each one requires, read either:

- The protocol definition in `nest_core.layers.<layer>`, or
- The reference implementation under
  `packages/nest-plugins-reference/nest_plugins_reference/<layer>/`.

For this walkthrough, we'll write a **payments** plugin that charges a
flat 10-credit fee per service.

## Step 2: Implement the interface

```python
# my_payments/plugin.py
# SPDX-License-Identifier: Apache-2.0
"""Flat-fee payments plugin — charges a constant per-service fee."""

from __future__ import annotations

from nest_sdk import (
    AgentId,
    Money,
    PaymentRef,
    PaymentStatus,
    Quote,
    Receipt,
    ServiceRef,
)


class FlatFeePayments:
    """Charges a constant fee for any service. In-memory ledger."""

    def __init__(self, agent_id: AgentId, fee: int = 10) -> None:
        self._me = agent_id
        self._fee = fee
        self._receipts: dict[PaymentRef, Receipt] = {}

    async def quote(self, service: ServiceRef) -> Quote:
        return Quote(service=service, price=Money(amount=self._fee))

    async def pay(
        self, to: AgentId, amount: Money, ref: PaymentRef,
    ) -> Receipt:
        receipt = Receipt(ref=ref, payer=self._me, payee=to, amount=amount)
        self._receipts[ref] = receipt
        return receipt

    async def verify_payment(self, ref: PaymentRef) -> PaymentStatus:
        return PaymentStatus.CONFIRMED if ref in self._receipts else PaymentStatus.FAILED

    async def refund(self, ref: PaymentRef) -> None:
        self._receipts.pop(ref, None)
```

A few things worth noting:

- **No base class.** The `Payments` interface is a `typing.Protocol`,
  so structural matching is enough. (You *can* inherit from
  `nest_sdk.Payments` for editor support; it's optional.)
- **Import from `nest_sdk`.** That's the stable public surface for
  plugin authors. Don't import from `nest_core.types` directly.
- **No magic.** This class is plain Python — you can unit-test it
  without touching Nanda Town at all.

## Step 3: Register an entry point

```toml
# pyproject.toml
[project]
name = "my-payments"
version = "0.1.0"
dependencies = ["nest-sdk"]

[project.entry-points."nest.plugins.payments"]
flat_fee = "my_payments.plugin:FlatFeePayments"
```

The entry point group must be `nest.plugins.<layer>`. The name on the
left (`flat_fee`) is what scenarios use; the value on the right is
`module:Class`.

## Step 4: Install

```bash
pip install -e .
```

Verify Nanda Town sees it:

```bash
nest plugins list | grep -A1 payments
# payments:
#   - flat_fee
#   - prepaid_credits
```

## Step 5: Use it in a scenario

```bash
nest scenarios cp marketplace ./my-marketplace.yaml
```

Open `my-marketplace.yaml` and change one line:

```yaml
layers:
  payments: prepaid_credits   # ← change to:
  payments: flat_fee
```

Run it:

```bash
nest run ./my-marketplace.yaml -o ./traces/flat-fee.jsonl
```

## Step 6: Compare against a baseline

```bash
nest run marketplace        -o ./traces/baseline.jsonl
nest run ./my-marketplace.yaml -o ./traces/flat-fee.jsonl

nest report ./traces/baseline.jsonl  -o report-baseline.html
nest report ./traces/flat-fee.jsonl  -o report-flat-fee.html

python -c "
from pathlib import Path
from nest_core.validators import validate_trace
for r in validate_trace(Path('traces/flat-fee.jsonl'), 'marketplace'):
    print(('PASS' if r.passed else 'FAIL'), r.name, '-', r.detail)
"
```

That's the whole loop: implement, register, install, swap in a
scenario, run, compare. Iterate by changing `failures.message_drop`,
agent count, or `failures.byzantine_agents` and re-running.

## Testing your plugin

Nanda Town does **not** currently ship a `nest plugins conform` command.
Treat your plugin like any other Python module:

```python
# tests/test_flat_fee.py
import pytest
from nest_sdk import AgentId, Money, PaymentRef, PaymentStatus, ServiceRef
from my_payments.plugin import FlatFeePayments

@pytest.mark.asyncio
async def test_quote_uses_configured_fee() -> None:
    p = FlatFeePayments(AgentId("a"), fee=42)
    quote = await p.quote(ServiceRef("svc"))
    assert quote.price.amount == 42

@pytest.mark.asyncio
async def test_pay_then_verify() -> None:
    p = FlatFeePayments(AgentId("alice"))
    ref = PaymentRef("r1")
    await p.pay(AgentId("bob"), Money(amount=10), ref)
    assert await p.verify_payment(ref) == PaymentStatus.CONFIRMED
```

For higher-confidence checks, run your plugin through a full scenario
and assert the resulting trace satisfies the relevant validators in
`nest_core.validators`.

## Plugins for other layers

Every layer follows the same recipe — only the interface changes:

| Layer | Interface (in `nest_sdk`) | Reference plugin to copy |
|---|---|---|
| transport | `Transport` | `nest_plugins_reference.transport.in_memory` |
| comms | `CommsProtocol` | `nest_plugins_reference.comms.nest_native` |
| identity | `Identity` | `nest_plugins_reference.identity.did_key` |
| registry | `Registry` | `nest_plugins_reference.registry.in_memory` |
| auth | `Auth` | `nest_plugins_reference.auth.jwt_auth` |
| trust | `Trust` | `nest_plugins_reference.trust.score_average` |
| payments | `Payments` | `nest_plugins_reference.payments.prepaid_credits` |
| coordination | `Coordination` | `nest_plugins_reference.coordination.contract_net` |
| negotiation | `Negotiation` | `nest_plugins_reference.negotiation.alternating_offers` |
| memory | `Memory` | `nest_plugins_reference.memory.blackboard` |
| privacy | `Privacy` | `nest_plugins_reference.privacy.noop` |
| datafacts | `DataFacts` | `nest_plugins_reference.datafacts.datafacts_v1` |

Read the reference plugin for the layer you're targeting — it's the
shortest, most accurate spec.
