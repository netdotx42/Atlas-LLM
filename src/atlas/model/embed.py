import math
import re
import zlib

_TOKEN = re.compile(r"[a-z0-9_]+")
_DIMS = 64


def feature_hash(text: str, dims: int = _DIMS) -> list[float]:
    """Local feature-hash embedding. No download and no network."""
    vector = [0.0] * dims
    tokens = _TOKEN.findall(text.lower())
    if not tokens:
        return vector
    for token in tokens:
        raw = token.encode()
        bucket = zlib.crc32(raw) % dims
        sign = 1.0 if zlib.crc32(b"\x01" + raw) % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def rank_columns(question: str, columns: list[str]) -> list[str]:
    query = feature_hash(question)
    scored = [(cosine(query, feature_hash(name)), name) for name in columns]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [name for _score, name in scored]
