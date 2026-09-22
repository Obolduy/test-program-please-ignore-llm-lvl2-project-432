import re

_PUNCTUATION = re.compile(r"[.,;:«»\"'()\[\]\-–—]")
_SPACES = re.compile(r"[\s ]+")


def normalize_value(value: object) -> str:
    text = str(value).lower().strip()
    text = _PUNCTUATION.sub("", text)
    return _SPACES.sub("", text)


def _matches(expected: str, actual: str) -> bool:
    return expected == actual or expected in actual or actual in expected


def field_accuracy(card: dict[str, str], golden: dict[str, str]) -> float:
    if not golden:
        return 1.0
    normalized = {normalize_value(k): normalize_value(v) for k, v in card.items()}
    hits = 0
    for key, value in golden.items():
        want_key, want_value = normalize_value(key), normalize_value(value)
        if normalized.get(want_key) == want_value:
            hits += 1
            continue
        hits += any(
            _matches(want_key, got_key) and _matches(want_value, got_value)
            for got_key, got_value in normalized.items()
        )
    return hits / len(golden)


def citation_hit(sources: list[dict], probes: dict, chunks_by_id: dict) -> float:
    if not probes:
        return 1.0
    claimed = [source["chunk_id"] for source in sources]
    hits = 0
    for probe in probes.values():
        expected = normalize_value(probe["text_contains"])
        hits += any(
            expected in normalize_value(chunks_by_id[chunk_id]["text"])
            for chunk_id in claimed
            if chunk_id in chunks_by_id
        )
    return hits / len(probes)
