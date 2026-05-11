"""Holographic Reduced Representations (HRR) with phase encoding.

Phase vectors: each concept is a list of angles in [0, 2π).
  bind   — circular convolution (phase addition)  — associates two concepts
  unbind — circular correlation (phase subtraction) — retrieves a bound value
  bundle — superposition (circular mean)           — merges multiple concepts

Atoms are generated deterministically from SHA-256 for reproducibility.
"""

import cmath
import hashlib
import logging
import math
import struct
from functools import lru_cache

logger = logging.getLogger(__name__)

_TWO_PI = 2.0 * math.pi


@lru_cache(maxsize=2048)
def encode_atom(word: str, dim: int = 1024) -> list[float]:
    """Deterministic phase vector via SHA-256 counter blocks."""
    values_per_block = 16
    blocks_needed = math.ceil(dim / values_per_block)
    uint16_values: list[int] = []
    for i in range(blocks_needed):
        digest = hashlib.sha256(f"{word}:{i}".encode()).digest()
        uint16_values.extend(struct.unpack("<16H", digest))
    return [x * (_TWO_PI / 65536.0) for x in uint16_values[:dim]]


def bind(a: list[float], b: list[float]) -> list[float]:
    """Circular convolution = element-wise phase addition. Associates two concepts."""
    return [(x + y) % _TWO_PI for x, y in zip(a, b)]


def unbind(memory: list[float], key: list[float]) -> list[float]:
    """Circular correlation = element-wise phase subtraction. Retrieves bound value."""
    return [(x - y) % _TWO_PI for x, y in zip(memory, key)]


def bundle(*vectors: list[float]) -> list[float]:
    """Superposition via circular mean. Merges multiple vectors into one."""
    dim = len(vectors[0])
    result = []
    for i in range(dim):
        c = sum(cmath.exp(1j * v[i]) for v in vectors)
        result.append(cmath.phase(c) % _TWO_PI)
    return result


def similarity(a: list[float], b: list[float]) -> float:
    """Phase cosine similarity. Range [-1, 1]."""
    n = len(a)
    return sum(math.cos(x - y) for x, y in zip(a, b)) / n


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "could", "may", "might", "must", "can", "of", "in", "on", "at", "to",
    "for", "with", "by", "from", "as", "and", "or", "but", "if", "then",
    "this", "that", "these", "those", "it", "its", "i", "you", "we",
    "they", "he", "she", "my", "your", "our", "their", "his", "her", "me",
    "us", "them", "so", "not", "no", "yes",
})


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, stripping punctuation and stopwords."""
    return [
        t for t in (w.strip(".,!?;:\"'()[]{}#@<>") for w in text.lower().split())
        if t and t not in _STOPWORDS
    ]


def encode_text(text: str, dim: int = 1024) -> list[float]:
    """Bag-of-words: bundle of atom vectors for each token."""
    tokens = tokenize(text)
    if not tokens:
        return encode_atom("__hrr_empty__", dim)
    return bundle(*[encode_atom(token, dim) for token in tokens])


def encode_fact(content: str, entities: list[str], dim: int = 1024) -> list[float]:
    """Structured encoding: content bound to ROLE_CONTENT, entities bound to ROLE_ENTITY."""
    role_content = encode_atom("__hrr_role_content__", dim)
    role_entity = encode_atom("__hrr_role_entity__", dim)
    components: list[list[float]] = [bind(encode_text(content, dim), role_content)]
    for entity in entities:
        components.append(bind(encode_atom(entity.lower(), dim), role_entity))
    return bundle(*components)


def phases_to_bytes(phases: list[float]) -> bytes:
    """Serialize phase vector to bytes (8 KB at dim=1024)."""
    return struct.pack(f"{len(phases)}d", *phases)


def bytes_to_phases(data: bytes) -> list[float]:
    """Deserialize bytes back to phase vector."""
    n = len(data) // 8
    return list(struct.unpack(f"{n}d", data))


def snr_estimate(dim: int, n_items: int) -> float:
    """Signal-to-noise ratio estimate. Logs warning when SNR < 2.0."""
    if n_items <= 0:
        return float("inf")
    snr = math.sqrt(dim / n_items)
    if snr < 2.0:
        logger.warning(
            "HRR near capacity: SNR=%.2f (dim=%d, n=%d). Consider increasing dim.",
            snr, dim, n_items,
        )
    return snr
