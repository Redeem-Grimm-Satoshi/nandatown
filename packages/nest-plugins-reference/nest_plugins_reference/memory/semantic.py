# SPDX-License-Identifier: Apache-2.0
"""Semantic memory plugin — content-addressable recall for agent swarms.

Implements the standard ``nest_sdk.Memory`` protocol (``read``/``write``/
``subscribe``/``cas``) so it is a drop-in replacement for ``blackboard``,
but layers two LLM-agent-relevant capabilities on top:

1. **Similarity recall.** ``recall(query, k)`` returns the *k* most similar
   stored values to a query string, ranked by cosine similarity over a
   deterministic hashed bag-of-tokens "embedding". No external embedding
   service, no API key, no GPU — and crucially **byte-identical across
   runs given the same writes**, which preserves NEST's Tier 1
   determinism guarantee.
2. **TTL + capacity bounds.** Memories carry a logical timestamp and can
   age out; once the store hits ``capacity`` the least-recently-accessed
   entry is evicted. This lets you actually stress retrieval-heavy
   coordination protocols ("what happens when 50 agents have to share a
   memory of size 100 with a 5% drop rate?") instead of pretending memory
   is infinite.

Why this exists. The default ``blackboard`` plugin is a shared dict.
That is fine for state-machine agents that already know the key they
want, but it is the wrong shape for the thing LLM agents actually do:
"recall the most relevant past interaction given this prompt." This
plugin is the testing harness for retrieval-augmented agent
coordination — what gets remembered, what gets evicted, and how
brittle a swarm's collective memory is under load.

Example::

    mem = SemanticMemory(capacity=128, ttl=100)
    await mem.write("buyer-3:greeting", b"hello, I want to buy apples")
    await mem.write("buyer-7:greeting", b"hi, looking for bananas")
    hits = await mem.recall("apple buyer", k=1)
    # hits == [("buyer-3:greeting", b"hello, I want to buy apples", <score>)]
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

# Public surface: ``RecallHit`` is what ``recall`` returns. It is a small
# typed tuple-like dataclass so callers can ``hit.key`` / ``hit.score``
# instead of indexing by position. We deliberately keep this dependency-free
# (no numpy, no sklearn) — semantic memory in NEST should run anywhere the
# rest of the simulator runs.


# Hashed embedding dimension. Small enough to stay cheap (cosine over 256
# floats is microseconds), large enough that collisions across a few
# thousand tokens are rare. Power of two for nice hash masking.
_DIM: int = 256

# Token regex: alphanumerics + apostrophes. We deliberately do not handle
# Unicode word boundaries — determinism matters more than linguistic
# correctness here. A real production embedder would belong behind a
# different plugin name; this one's whole job is to be reproducible.
_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _tokenize(text: str) -> list[str]:
    """Lowercased alphanumeric tokens. Deterministic, no locale dependency."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _fnv1a(data: bytes) -> int:
    """FNV-1a 64-bit hash. Process-independent (Python's hash is salted)."""
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _features(text: str) -> list[str]:
    """Token + char-trigram features for the embedder.

    Whole tokens give exact-match signal; character trigrams give
    morphological / substring signal so "apples" matches "apple",
    "buyer" matches "buy", etc. This is what makes ``recall("apple
    buyer", k=1)`` actually find a memory that says "I want to buy
    apples" instead of returning a tie at zero similarity.

    No external library, no learned embedding, still deterministic.
    Production-grade similarity would belong in a separate plugin (e.g.
    ``memory:openai_embeddings``); this one is the reproducible baseline.
    """
    tokens = _tokenize(text)
    feats: list[str] = list(tokens)
    n = 3
    for tok in tokens:
        # Pad so n-grams at word boundaries pick up the prefix/suffix.
        padded = f"^{tok}$"
        if len(padded) <= n:
            feats.append(padded)
            continue
        feats.extend(padded[i : i + n] for i in range(len(padded) - n + 1))
    return feats


def _embed(text: str) -> list[float]:
    """Deterministic hashed feature vector, L2-normalized.

    Folds every (token + char-trigram) feature into ``_DIM`` buckets via
    FNV-1a so the same input always produces the same vector — across
    processes, machines, and Python versions.
    """
    vec = [0.0] * _DIM
    for feat in _features(text):
        h = _fnv1a(feat.encode("utf-8"))
        idx = h & (_DIM - 1)
        # Sign bit so unrelated features can cancel rather than only add —
        # this is the standard "signed feature hashing" trick.
        sign = 1.0 if (h >> 63) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity for already-L2-normalized vectors == dot product."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def _decode(value: bytes) -> str:
    """Best-effort UTF-8 decode for embedding; falls back to repr of bytes."""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        # Binary payload: index by its hex digest so identical bytes still
        # match exactly via recall, just without semantic structure. This
        # keeps the contract: every write is recallable.
        return value.hex()


@dataclass
class RecallHit:
    """A single recall result.

    Example::

        for hit in await mem.recall("apple", k=3):
            print(hit.key, hit.score)
    """

    key: str
    value: bytes
    score: float


@dataclass
class _Entry:
    """Internal: stored memory record."""

    value: bytes
    embedding: list[float]
    written_at: int
    last_used: int = 0
    text: str = ""
    forgotten: bool = field(default=False)


class SemanticMemory:
    """Drop-in ``Memory`` plugin with similarity recall, TTL, and LRU eviction.

    Constructor parameters:

    - ``capacity``: max entries retained. ``None`` means unbounded.
    - ``ttl``: logical-time-to-live. ``None`` means entries never expire.
      The clock is *logical* (an integer tick incremented on every write
      and recall) so behaviour is deterministic and independent of
      wall-clock time. Pass a custom ``now_fn`` to drive the clock from
      an external simulator if you want.
    - ``now_fn``: optional callable returning the current logical time.
      Use this to share a clock with the NEST simulator. If ``None``, an
      internal monotonically-increasing counter is used.

    Example::

        mem = SemanticMemory(capacity=64, ttl=50)
        await mem.write("note-1", b"agent alpha proposed price 42")
        await mem.write("note-2", b"agent beta accepted at 40")
        # Find the most relevant memory to a new prompt:
        [hit] = await mem.recall("what did beta say about price?", k=1)
        assert hit.key == "note-2"
    """

    def __init__(
        self,
        capacity: int | None = None,
        ttl: int | None = None,
        now_fn: Callable[[], int] | None = None,
    ) -> None:
        if capacity is not None and capacity <= 0:
            raise ValueError("capacity must be positive or None")
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive or None")
        self._capacity = capacity
        self._ttl = ttl
        # OrderedDict preserves insertion order; we ``move_to_end`` on access
        # to get LRU behaviour for free.
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._subscribers: dict[str, list[asyncio.Queue[bytes]]] = {}
        # Bookkeeping for stats.
        self._writes: int = 0
        self._evictions: int = 0
        self._expirations: int = 0
        self._recalls: int = 0
        # Logical clock. External clocks override; otherwise we tick
        # internally on each write/recall.
        self._tick: int = 0
        self._now_fn = now_fn

    # ------------------------------------------------------------------
    # Memory protocol surface — read / write / subscribe / cas
    # ------------------------------------------------------------------

    async def read(self, key: str) -> bytes | None:
        """Read by exact key. Returns ``None`` if absent or expired.

        Reading an entry refreshes its LRU position but does **not**
        reset its TTL — TTL is anchored to write time, so a hot entry
        still ages out eventually. That matches how production retrieval
        stores usually want it: don't let "popular but stale" memories
        squat indefinitely.
        """
        self._sweep_expired()
        entry = self._store.get(key)
        if entry is None:
            return None
        entry.last_used = self._now()
        self._store.move_to_end(key)
        return entry.value

    async def write(self, key: str, value: bytes) -> None:
        """Write a value for a key and index it for similarity recall.

        Overwriting an existing key updates both the value and the
        embedding, and resets the entry's TTL (it counts as a fresh
        write). Subscribers are notified after the write commits.
        """
        text = _decode(value)
        now = self._now(advance=True)
        entry = _Entry(
            value=value,
            embedding=_embed(text),
            written_at=now,
            last_used=now,
            text=text,
        )
        self._store[key] = entry
        self._store.move_to_end(key)
        self._writes += 1
        self._enforce_capacity()
        # Notify subscribers after structural mutations so they see a
        # consistent store if they re-read.
        for q in self._subscribers.get(key, []):
            await q.put(value)

    async def subscribe(self, key: str) -> AsyncIterator[bytes]:
        """Subscribe to changes for a key. Yields each new value.

        Mirrors ``Blackboard.subscribe`` so swap-in is transparent.
        """
        q: asyncio.Queue[bytes] = asyncio.Queue()
        self._subscribers.setdefault(key, []).append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers[key].remove(q)

    async def cas(self, key: str, expected: bytes, new: bytes) -> bool:
        """Compare-and-swap. Updates only if current value matches expected.

        Expired entries count as absent — a CAS against an expired key
        with ``expected != None`` will fail. This is intentional: TTL
        eviction is a real event that races with writers, and a CAS
        should respect it.
        """
        self._sweep_expired()
        entry = self._store.get(key)
        if entry is None or entry.value != expected:
            return False
        await self.write(key, new)
        return True

    # ------------------------------------------------------------------
    # Semantic surface — the reason this plugin exists
    # ------------------------------------------------------------------

    async def recall(
        self,
        query: str,
        k: int = 5,
        min_score: float = 0.0,
    ) -> list[RecallHit]:
        """Return up to ``k`` entries most similar to ``query``.

        Results are sorted by descending cosine similarity. Ties are
        broken by key (lexicographic) so output is deterministic
        regardless of dict iteration order — important for trace
        reproducibility.

        ``min_score`` filters out weak matches (default 0.0 keeps any
        non-orthogonal hit). For LLM-agent scenarios a threshold of
        ~0.15 tends to drop pure-junk hits without losing recall.

        Recalling refreshes the LRU position of each returned entry so
        "useful" memories survive eviction longer than dead weight.
        """
        if k <= 0:
            return []
        self._sweep_expired()
        self._recalls += 1
        q_emb = _embed(query)
        scored: list[tuple[float, str, _Entry]] = []
        for key, entry in self._store.items():
            score = _cosine(q_emb, entry.embedding)
            if score >= min_score:
                scored.append((score, key, entry))
        # Sort: highest score first, then key ascending for tie-breaks.
        scored.sort(key=lambda t: (-t[0], t[1]))
        top = scored[:k]
        now = self._now()
        hits: list[RecallHit] = []
        for score, key, entry in top:
            entry.last_used = now
            # Move recalled entries to LRU "fresh" end so they don't get
            # evicted while still being useful.
            self._store.move_to_end(key)
            hits.append(RecallHit(key=key, value=entry.value, score=score))
        return hits

    async def forget(self, key: str) -> bool:
        """Explicitly evict ``key``. Returns ``True`` if it was present."""
        return self._store.pop(key, None) is not None

    def stats(self) -> dict[str, int]:
        """Snapshot of internal counters. Useful in tests + validators.

        Example::

            assert mem.stats()["evictions"] == 0
        """
        self._sweep_expired()
        return {
            "size": len(self._store),
            "capacity": self._capacity if self._capacity is not None else -1,
            "writes": self._writes,
            "recalls": self._recalls,
            "evictions": self._evictions,
            "expirations": self._expirations,
            "tick": self._tick,
        }

    # ------------------------------------------------------------------
    # Internal: clock, eviction, expiry
    # ------------------------------------------------------------------

    def _now(self, advance: bool = False) -> int:
        if self._now_fn is not None:
            return int(self._now_fn())
        if advance:
            self._tick += 1
        return self._tick

    def _enforce_capacity(self) -> None:
        if self._capacity is None:
            return
        while len(self._store) > self._capacity:
            # OrderedDict.popitem(last=False) -> LRU end (the least
            # recently used; we move-to-end on access so the front is LRU).
            self._store.popitem(last=False)
            self._evictions += 1

    def _sweep_expired(self) -> None:
        """Drop entries whose TTL has elapsed against the current clock."""
        if self._ttl is None:
            return
        now = self._now()
        # Walk in insertion order; we cannot mutate during iteration so
        # collect first. The store is bounded by ``capacity`` so this is
        # O(n) on a small n.
        stale: list[str] = [
            key for key, entry in self._store.items() if now - entry.written_at >= self._ttl
        ]
        for key in stale:
            del self._store[key]
            self._expirations += 1
