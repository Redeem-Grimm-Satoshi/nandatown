# SPDX-License-Identifier: Apache-2.0
"""Conformance tests for all 12 reference plugins."""

from __future__ import annotations

import pytest
from nest_core.types import (
    AgentCard,
    AgentId,
    DatasetMetadata,
    Evidence,
    Message,
    MessageId,
    Money,
    NegotiationStatus,
    PaymentRef,
    PaymentStatus,
    Query,
    Receipt,
    ServiceRef,
    Statement,
    Task,
    Terms,
    Witness,
)

# ---------------------------------------------------------------------------
# 1. Transport: in_memory
# ---------------------------------------------------------------------------


class TestInMemoryTransport:
    @pytest.mark.asyncio
    async def test_send_receive(self) -> None:
        from nest_plugins_reference.transport.in_memory import (
            InMemoryNetwork,
            StandaloneInMemoryTransport,
        )

        network = InMemoryNetwork()
        t1 = StandaloneInMemoryTransport(AgentId("a1"), network)
        t2 = StandaloneInMemoryTransport(AgentId("a2"), network)

        await t1.send(AgentId("a2"), b"hello")
        sender, payload = await t2.receive()
        assert sender == AgentId("a1")
        assert payload == b"hello"

    @pytest.mark.asyncio
    async def test_broadcast(self) -> None:
        from nest_plugins_reference.transport.in_memory import (
            InMemoryNetwork,
            StandaloneInMemoryTransport,
        )

        network = InMemoryNetwork()
        t1 = StandaloneInMemoryTransport(AgentId("a1"), network)
        t2 = StandaloneInMemoryTransport(AgentId("a2"), network)
        t3 = StandaloneInMemoryTransport(AgentId("a3"), network)

        await t1.broadcast(b"announce")
        _, p2 = await t2.receive()
        _, p3 = await t3.receive()
        assert p2 == b"announce"
        assert p3 == b"announce"


# ---------------------------------------------------------------------------
# 2. Comms: nest_native
# ---------------------------------------------------------------------------


class TestNestNativeComms:
    def test_serialize_deserialize(self) -> None:
        from nest_plugins_reference.comms.nest_native import NestNativeComms

        comms = NestNativeComms(AgentId("a1"))
        msg = Message(
            id=MessageId("m1"),
            sender=AgentId("a1"),
            receiver=AgentId("a2"),
            payload=b"test data",
        )
        raw = comms.serialize(msg)
        msg2 = comms.deserialize(raw)
        assert msg2.id == msg.id
        assert msg2.sender == msg.sender
        assert msg2.payload == msg.payload

    @pytest.mark.asyncio
    async def test_send(self) -> None:
        from nest_plugins_reference.comms.nest_native import NestNativeComms

        comms = NestNativeComms(AgentId("a1"))
        msg = Message(
            id=MessageId("m1"),
            sender=AgentId("a1"),
            receiver=AgentId("a2"),
            payload=b"test",
        )
        resp = await comms.send(AgentId("a2"), msg)
        assert resp.success is True


# ---------------------------------------------------------------------------
# 3. Identity: did_key
# ---------------------------------------------------------------------------


class TestDidKeyIdentity:
    def test_sign_verify(self) -> None:
        from nest_plugins_reference.identity.did_key import DidKeyIdentity

        ident = DidKeyIdentity(AgentId("a1"), seed=b"seed")
        sig = ident.sign(b"payload")
        assert sig.signer == AgentId("a1")
        assert ident.verify(b"payload", sig, AgentId("a1"))

    def test_verify_wrong_payload(self) -> None:
        from nest_plugins_reference.identity.did_key import DidKeyIdentity

        ident = DidKeyIdentity(AgentId("a1"), seed=b"seed")
        sig = ident.sign(b"payload")
        assert not ident.verify(b"wrong", sig, AgentId("a1"))

    def test_verify_peer_with_public_key_only(self) -> None:
        from nest_plugins_reference.identity.did_key import DidKeyIdentity

        sender = DidKeyIdentity(AgentId("a1"), seed=b"seed")
        verifier = DidKeyIdentity(AgentId("a2"), seed=b"seed")
        verifier.register_peer(AgentId("a1"), sender.public_key)

        sig = sender.sign(b"payload")
        assert verifier.verify(b"payload", sig, AgentId("a1"))

    def test_register_peer_rejects_private_key(self) -> None:
        from nest_plugins_reference.identity.did_key import DidKeyIdentity

        ident = DidKeyIdentity(AgentId("a1"), seed=b"seed")
        with pytest.raises(ValueError, match="public keys only"):
            ident.register_peer(AgentId("a2"), ident.public_key, private_key=b"secret")

    @pytest.mark.asyncio
    async def test_resolve(self) -> None:
        from nest_plugins_reference.identity.did_key import DidKeyIdentity

        ident = DidKeyIdentity(AgentId("a1"), seed=b"seed")
        info = await ident.resolve(AgentId("a1"))
        assert info.agent_id == AgentId("a1")
        assert info.method == "did:key"
        assert len(info.public_key) > 0


# ---------------------------------------------------------------------------
# 4. Registry: in_memory
# ---------------------------------------------------------------------------


class TestInMemoryRegistry:
    @pytest.mark.asyncio
    async def test_register_lookup(self) -> None:
        from nest_plugins_reference.registry.in_memory import InMemoryRegistry

        reg = InMemoryRegistry()
        card = AgentCard(agent_id=AgentId("a1"), name="Seller", capabilities=["sell"])
        await reg.register(card)

        results = await reg.lookup(Query(capabilities=["sell"]))
        assert len(results) == 1
        assert results[0].agent_id == AgentId("a1")

    @pytest.mark.asyncio
    async def test_lookup_no_match(self) -> None:
        from nest_plugins_reference.registry.in_memory import InMemoryRegistry

        reg = InMemoryRegistry()
        card = AgentCard(agent_id=AgentId("a1"), name="Buyer", capabilities=["buy"])
        await reg.register(card)

        results = await reg.lookup(Query(capabilities=["sell"]))
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_deregister(self) -> None:
        from nest_plugins_reference.registry.in_memory import InMemoryRegistry

        reg = InMemoryRegistry()
        card = AgentCard(agent_id=AgentId("a1"), name="Agent", capabilities=["x"])
        await reg.register(card)
        await reg.deregister(AgentId("a1"))

        results = await reg.lookup(Query())
        assert len(results) == 0


# ---------------------------------------------------------------------------
# 5. Auth: jwt
# ---------------------------------------------------------------------------


class TestJwtAuth:
    @pytest.mark.asyncio
    async def test_issue_verify(self) -> None:
        from nest_plugins_reference.auth.jwt_auth import JwtAuth

        auth = JwtAuth(secret=b"test-secret")
        token = await auth.issue(AgentId("a1"), ["read", "write"])
        ctx = await auth.verify(token)
        assert ctx.subject == AgentId("a1")
        assert ctx.scopes == ["read", "write"]

    @pytest.mark.asyncio
    async def test_revoke(self) -> None:
        from nest_plugins_reference.auth.jwt_auth import JwtAuth

        auth = JwtAuth(secret=b"test-secret")
        token = await auth.issue(AgentId("a1"), ["read"])
        await auth.revoke(token)
        with pytest.raises(ValueError, match="revoked"):
            await auth.verify(token)

    @pytest.mark.asyncio
    async def test_invalid_signature(self) -> None:
        from nest_plugins_reference.auth.jwt_auth import JwtAuth

        auth = JwtAuth(secret=b"secret1")
        token = await auth.issue(AgentId("a1"), ["read"])

        auth2 = JwtAuth(secret=b"secret2")
        with pytest.raises(ValueError, match="signature"):
            await auth2.verify(token)


# ---------------------------------------------------------------------------
# 6. Trust: score_average
# ---------------------------------------------------------------------------


class TestScoreAverageTrust:
    @pytest.mark.asyncio
    async def test_default_score(self) -> None:
        from nest_plugins_reference.trust.score_average import ScoreAverageTrust

        trust = ScoreAverageTrust()
        score = await trust.score(AgentId("a1"))
        assert score.score == 0.5
        assert score.confidence == 0.0
        assert score.sample_count == 0

    @pytest.mark.asyncio
    async def test_report_updates_score(self) -> None:
        from nest_plugins_reference.trust.score_average import ScoreAverageTrust

        trust = ScoreAverageTrust()
        ev = Evidence(reporter=AgentId("a2"), subject=AgentId("a1"), kind="positive")
        await trust.report(AgentId("a1"), ev)
        await trust.report(AgentId("a1"), ev)

        score = await trust.score(AgentId("a1"))
        assert score.score == 1.0
        assert score.sample_count == 2

    @pytest.mark.asyncio
    async def test_negative_report(self) -> None:
        from nest_plugins_reference.trust.score_average import ScoreAverageTrust

        trust = ScoreAverageTrust()
        pos = Evidence(reporter=AgentId("a2"), subject=AgentId("a1"), kind="positive")
        neg = Evidence(reporter=AgentId("a3"), subject=AgentId("a1"), kind="negative")
        await trust.report(AgentId("a1"), pos)
        await trust.report(AgentId("a1"), neg)

        score = await trust.score(AgentId("a1"))
        assert score.score == 0.5


# ---------------------------------------------------------------------------
# 7. Payments: prepaid_credits
# ---------------------------------------------------------------------------


class TestPrepaidCredits:
    @pytest.mark.asyncio
    async def test_pay_and_verify(self) -> None:
        from nest_plugins_reference.payments.prepaid_credits import PrepaidCredits

        pay = PrepaidCredits(AgentId("a1"), initial_balance=1000)
        receipt = await pay.pay(AgentId("a2"), Money(amount=100), PaymentRef("p1"))
        assert receipt.payer == AgentId("a1")
        assert receipt.payee == AgentId("a2")
        assert pay.balance(AgentId("a1")) == 900
        assert pay.balance(AgentId("a2")) == 100

        status = await pay.verify_payment(PaymentRef("p1"))
        assert status == PaymentStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_insufficient_balance(self) -> None:
        from nest_plugins_reference.payments.prepaid_credits import PrepaidCredits

        pay = PrepaidCredits(AgentId("a1"), initial_balance=10)
        with pytest.raises(ValueError, match="Insufficient"):
            await pay.pay(AgentId("a2"), Money(amount=100), PaymentRef("p1"))

    @pytest.mark.asyncio
    async def test_refund(self) -> None:
        from nest_plugins_reference.payments.prepaid_credits import PrepaidCredits

        pay = PrepaidCredits(AgentId("a1"), initial_balance=1000)
        await pay.pay(AgentId("a2"), Money(amount=100), PaymentRef("p1"))
        await pay.refund(PaymentRef("p1"))
        assert pay.balance(AgentId("a1")) == 1000
        assert pay.balance(AgentId("a2")) == 0

    @pytest.mark.asyncio
    async def test_quote(self) -> None:
        from nest_plugins_reference.payments.prepaid_credits import PrepaidCredits

        pay = PrepaidCredits(AgentId("a1"))
        q = await pay.quote(ServiceRef("svc"))
        assert q.price.amount == 10

    @pytest.mark.asyncio
    async def test_shared_ledger_debits_calling_agent(self) -> None:
        from nest_plugins_reference.payments.prepaid_credits import PrepaidCredits

        balances = {AgentId("buyer"): 100, AgentId("seller"): 0}
        payments: dict[PaymentRef, Receipt] = {}
        buyer = PrepaidCredits(AgentId("buyer"), balances=balances, payments=payments)
        seller = PrepaidCredits(AgentId("seller"), balances=balances, payments=payments)

        await buyer.pay(AgentId("seller"), Money(amount=40), PaymentRef("p1"))

        assert buyer.balance(AgentId("buyer")) == 60
        assert seller.balance(AgentId("seller")) == 40
        assert await seller.verify_payment(PaymentRef("p1")) == PaymentStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_rejects_non_positive_payment(self) -> None:
        from nest_plugins_reference.payments.prepaid_credits import PrepaidCredits

        pay = PrepaidCredits(AgentId("a1"), initial_balance=100)
        with pytest.raises(ValueError, match="positive"):
            await pay.pay(AgentId("a2"), Money(amount=0), PaymentRef("p1"))


# ---------------------------------------------------------------------------
# 8. Coordination: contract_net
# ---------------------------------------------------------------------------


class TestContractNet:
    @pytest.mark.asyncio
    async def test_propose_participate_resolve(self) -> None:
        from nest_plugins_reference.coordination.contract_net import ContractNet

        manager = ContractNet(AgentId("mgr"))
        worker1 = ContractNet(AgentId("w1"))
        worker2 = ContractNet(AgentId("w2"))

        task = Task(id="t1", description="process")
        rnd = await manager.propose(task)

        await worker1.participate(rnd)
        await worker2.participate(rnd)

        outcome = await manager.resolve(rnd)
        assert outcome.task.id == "t1"
        assert outcome.winner is not None

    @pytest.mark.asyncio
    async def test_commit_cleans_up(self) -> None:
        from nest_plugins_reference.coordination.contract_net import ContractNet

        coord = ContractNet(AgentId("a1"))
        task = Task(id="t1", description="work")
        rnd = await coord.propose(task)
        await coord.participate(rnd)
        outcome = await coord.resolve(rnd)
        await coord.commit(outcome)


# ---------------------------------------------------------------------------
# 9. Negotiation: alternating_offers
# ---------------------------------------------------------------------------


class TestAlternatingOffers:
    @pytest.mark.asyncio
    async def test_open_offer_respond_close(self) -> None:
        from nest_plugins_reference.negotiation.alternating_offers import AlternatingOffers

        neg = AlternatingOffers(AgentId("a1"))
        session = await neg.open(AgentId("a2"), Terms(price=Money(amount=100)))
        assert session.status == NegotiationStatus.OPEN

        await neg.offer(session, Terms(price=Money(amount=80)))
        resp = await neg.respond(session)
        assert isinstance(resp.accepted, bool)

        agreement = await neg.close(session)
        assert agreement is not None
        assert agreement.session_id == session.id

    @pytest.mark.asyncio
    async def test_no_terms(self) -> None:
        from nest_plugins_reference.negotiation.alternating_offers import AlternatingOffers

        neg = AlternatingOffers(AgentId("a1"))
        session = await neg.open(AgentId("a2"), Terms())
        resp = await neg.respond(session)
        assert resp.accepted is True


# ---------------------------------------------------------------------------
# 10. Memory: blackboard
# ---------------------------------------------------------------------------


class TestBlackboard:
    @pytest.mark.asyncio
    async def test_read_write(self) -> None:
        from nest_plugins_reference.memory.blackboard import Blackboard

        bb = Blackboard()
        assert await bb.read("key") is None
        await bb.write("key", b"value")
        assert await bb.read("key") == b"value"

    @pytest.mark.asyncio
    async def test_cas_success(self) -> None:
        from nest_plugins_reference.memory.blackboard import Blackboard

        bb = Blackboard()
        await bb.write("x", b"old")
        assert await bb.cas("x", b"old", b"new") is True
        assert await bb.read("x") == b"new"

    @pytest.mark.asyncio
    async def test_cas_failure(self) -> None:
        from nest_plugins_reference.memory.blackboard import Blackboard

        bb = Blackboard()
        await bb.write("x", b"current")
        assert await bb.cas("x", b"wrong", b"new") is False
        assert await bb.read("x") == b"current"


# ---------------------------------------------------------------------------
# 10b. Memory: semantic (similarity recall + TTL + LRU)
# ---------------------------------------------------------------------------


class TestSemanticMemory:
    @pytest.mark.asyncio
    async def test_read_write_matches_blackboard_contract(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        assert await mem.read("k") is None
        await mem.write("k", b"v")
        assert await mem.read("k") == b"v"

    @pytest.mark.asyncio
    async def test_cas_success_and_failure(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        await mem.write("x", b"old")
        assert await mem.cas("x", b"old", b"new") is True
        assert await mem.read("x") == b"new"
        assert await mem.cas("x", b"wrong", b"newer") is False
        assert await mem.read("x") == b"new"

    @pytest.mark.asyncio
    async def test_subscribe_receives_writes(self) -> None:
        import asyncio

        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        received: list[bytes] = []

        async def listener() -> None:
            async for v in mem.subscribe("topic"):
                received.append(v)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(listener())
        # Yield so the subscriber has time to register before we write.
        await asyncio.sleep(0)
        await mem.write("topic", b"first")
        await mem.write("topic", b"second")
        await asyncio.wait_for(task, timeout=1.0)
        assert received == [b"first", b"second"]

    @pytest.mark.asyncio
    async def test_recall_ranks_relevant_first(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        await mem.write("buyer-3:greet", b"hello, I want to buy apples")
        await mem.write("buyer-7:greet", b"hi, looking for bananas")
        await mem.write("buyer-9:greet", b"howdy, after some pears")

        hits = await mem.recall("apple buyer", k=1)
        assert len(hits) == 1
        assert hits[0].key == "buyer-3:greet"
        assert hits[0].score > 0.0

    @pytest.mark.asyncio
    async def test_recall_top_k_sorted_descending(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        await mem.write("a", b"apples bananas")
        await mem.write("b", b"apples oranges pears")
        await mem.write("c", b"unrelated zebra giraffe")

        hits = await mem.recall("apples", k=3)
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)
        # Best two should be the apple-mentioning ones.
        assert {hits[0].key, hits[1].key} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_recall_is_deterministic_across_runs(self) -> None:
        # Determinism is a load-bearing NEST property; semantic recall has
        # to satisfy it as well as exact-key reads do.
        from nest_plugins_reference.memory.semantic import SemanticMemory

        def make() -> SemanticMemory:
            return SemanticMemory()

        async def populate(mem: SemanticMemory) -> None:
            for i, text in enumerate(
                [
                    b"the auction closed at price forty two",
                    b"buyer accepted the offer of forty",
                    b"seller withdrew due to low bid",
                    b"observer noted nothing unusual",
                ]
            ):
                await mem.write(f"note-{i}", text)

        m1, m2 = make(), make()
        await populate(m1)
        await populate(m2)
        h1 = await m1.recall("what price was accepted?", k=4)
        h2 = await m2.recall("what price was accepted?", k=4)
        # Byte-identical results, score-for-score, key-for-key.
        assert [(h.key, h.value, h.score) for h in h1] == [(h.key, h.value, h.score) for h in h2]

    @pytest.mark.asyncio
    async def test_recall_min_score_filters_weak_matches(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        await mem.write("rel", b"apples and oranges")
        await mem.write("irr", b"zzz qqq xxx")
        # Threshold high enough to drop the unrelated (zero-overlap) one.
        # 0.15 is a defensible default for the hashed-trigram embedder: it
        # keeps hits with any meaningful substring overlap, drops pure noise.
        hits = await mem.recall("apple", k=5, min_score=0.15)
        assert len(hits) == 1
        assert hits[0].key == "rel"

    @pytest.mark.asyncio
    async def test_recall_k_zero_returns_empty(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        await mem.write("x", b"hello")
        assert await mem.recall("hello", k=0) == []

    @pytest.mark.asyncio
    async def test_capacity_evicts_lru(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory(capacity=2)
        await mem.write("a", b"first")
        await mem.write("b", b"second")
        # Touch a so it becomes most-recently-used.
        await mem.read("a")
        await mem.write("c", b"third")
        # b was LRU and should have been evicted.
        assert await mem.read("b") is None
        assert await mem.read("a") == b"first"
        assert await mem.read("c") == b"third"
        assert mem.stats()["evictions"] == 1

    @pytest.mark.asyncio
    async def test_recall_protects_from_eviction(self) -> None:
        # Recall should refresh LRU position for hits so "useful" memories
        # survive longer than dead weight under capacity pressure.
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory(capacity=2)
        await mem.write("a", b"apples")
        await mem.write("b", b"bananas")
        # Recall a: it's now most-recently-used.
        await mem.recall("apples", k=1)
        await mem.write("c", b"cherries")
        # b (oldest unused) should be evicted, not a.
        assert await mem.read("a") == b"apples"
        assert await mem.read("b") is None

    @pytest.mark.asyncio
    async def test_ttl_expires_entries(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        # Drive the clock externally so we can simulate elapsed time.
        clock = {"t": 0}
        mem = SemanticMemory(ttl=10, now_fn=lambda: clock["t"])
        await mem.write("x", b"hello")
        clock["t"] = 5
        assert await mem.read("x") == b"hello"
        clock["t"] = 10
        # TTL elapsed: entry should be swept out.
        assert await mem.read("x") is None
        assert mem.stats()["expirations"] == 1

    @pytest.mark.asyncio
    async def test_overwrite_resets_ttl(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        clock = {"t": 0}
        mem = SemanticMemory(ttl=10, now_fn=lambda: clock["t"])
        await mem.write("x", b"v1")
        clock["t"] = 9
        await mem.write("x", b"v2")
        clock["t"] = 18
        # Original write would have expired at t=10; the rewrite at t=9
        # pushes expiry to t=19, so the entry is still there at t=18.
        assert await mem.read("x") == b"v2"

    @pytest.mark.asyncio
    async def test_recall_skips_expired(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        clock = {"t": 0}
        mem = SemanticMemory(ttl=5, now_fn=lambda: clock["t"])
        await mem.write("old", b"apples in storage")
        clock["t"] = 3
        await mem.write("new", b"apples fresh today")
        clock["t"] = 6
        # "old" has expired; "new" is still fresh.
        hits = await mem.recall("apples", k=5)
        keys = [h.key for h in hits]
        assert "old" not in keys
        assert "new" in keys

    @pytest.mark.asyncio
    async def test_forget_removes_entry(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        await mem.write("x", b"v")
        assert await mem.forget("x") is True
        assert await mem.read("x") is None
        # Idempotent: second forget returns False.
        assert await mem.forget("x") is False

    @pytest.mark.asyncio
    async def test_stats_tracks_activity(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory(capacity=2)
        await mem.write("a", b"x")
        await mem.write("b", b"y")
        await mem.write("c", b"z")  # triggers one eviction
        await mem.recall("x", k=1)
        s = mem.stats()
        assert s["size"] == 2
        assert s["capacity"] == 2
        assert s["writes"] == 3
        assert s["evictions"] == 1
        assert s["recalls"] == 1

    @pytest.mark.asyncio
    async def test_binary_payloads_round_trip(self) -> None:
        # Non-UTF8 bytes shouldn't crash the embedder.
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        payload = bytes(range(256))
        await mem.write("blob", payload)
        assert await mem.read("blob") == payload
        # Recall still finds it (hex-indexed; identical bytes = exact match).
        hits = await mem.recall(payload.hex(), k=1)
        assert hits[0].key == "blob"

    def test_invalid_capacity_rejected(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        with pytest.raises(ValueError, match="capacity"):
            SemanticMemory(capacity=0)

    def test_invalid_ttl_rejected(self) -> None:
        from nest_plugins_reference.memory.semantic import SemanticMemory

        with pytest.raises(ValueError, match="ttl"):
            SemanticMemory(ttl=-1)

    def test_satisfies_memory_protocol(self) -> None:
        # Structural typing check: SemanticMemory should be a drop-in
        # replacement for Blackboard wherever the Memory protocol is used.
        from nest_core.layers.memory import Memory
        from nest_plugins_reference.memory.semantic import SemanticMemory

        mem = SemanticMemory()
        assert isinstance(mem, Memory)

    def test_registered_as_builtin_plugin(self) -> None:
        # The plugin registry should resolve ``memory:semantic`` to the
        # SemanticMemory class so YAML scenarios can use it by name.
        from nest_core.plugins import PluginRegistry
        from nest_plugins_reference.memory.semantic import SemanticMemory

        reg = PluginRegistry()
        cls = reg.resolve("memory", "semantic")
        assert cls is SemanticMemory


# ---------------------------------------------------------------------------
# 11. Privacy: noop
# ---------------------------------------------------------------------------


class TestNoopPrivacy:
    @pytest.mark.asyncio
    async def test_encrypt_decrypt_passthrough(self) -> None:
        from nest_plugins_reference.privacy.noop import NoopPrivacy

        priv = NoopPrivacy()
        ct = await priv.encrypt(b"secret", [AgentId("a1")])
        assert ct == b"secret"
        pt = await priv.decrypt(ct)
        assert pt == b"secret"

    @pytest.mark.asyncio
    async def test_prove_verify(self) -> None:
        from nest_plugins_reference.privacy.noop import NoopPrivacy

        priv = NoopPrivacy()
        stmt = Statement(predicate="test")
        witness = Witness(private_inputs={"x": "1"})
        proof = await priv.prove(stmt, witness)
        assert await priv.verify_proof(stmt, proof) is True


# ---------------------------------------------------------------------------
# 12. DataFacts: datafacts_v1
# ---------------------------------------------------------------------------


class TestDataFactsV1:
    @pytest.mark.asyncio
    async def test_publish_fetch(self) -> None:
        from nest_plugins_reference.datafacts.datafacts_v1 import DataFactsV1

        df = DataFactsV1()
        meta = DatasetMetadata(name="weather", owner=AgentId("a1"))
        url = await df.publish(meta)
        assert url == "df://weather"

        fetched = await df.fetch(url)
        assert fetched.name == "weather"
        assert fetched.owner == AgentId("a1")

    @pytest.mark.asyncio
    async def test_request_access(self) -> None:
        from nest_plugins_reference.datafacts.datafacts_v1 import DataFactsV1

        df = DataFactsV1()
        meta = DatasetMetadata(name="data", owner=AgentId("a1"))
        url = await df.publish(meta)
        grant = await df.request_access(url, AgentId("a2"))
        assert grant.grantee == AgentId("a2")
        assert grant.tier == "read"

    @pytest.mark.asyncio
    async def test_verify_freshness(self) -> None:
        from nest_plugins_reference.datafacts.datafacts_v1 import DataFactsV1

        df = DataFactsV1()
        meta = DatasetMetadata(name="fresh", owner=AgentId("a1"))
        url = await df.publish(meta)
        assert await df.verify_freshness(url) is True

    @pytest.mark.asyncio
    async def test_fetch_missing(self) -> None:
        from nest_core.types import DataFactsUrl
        from nest_plugins_reference.datafacts.datafacts_v1 import DataFactsV1

        df = DataFactsV1()
        with pytest.raises(KeyError):
            await df.fetch(DataFactsUrl("df://missing"))
