"""Load packaged postprocess lookup data.

The `postprocess-data.json` schema starts at version 1 and contains an integer
`schema_version`, a `LEXICON` object mapping regex pattern strings to canonical
replacements, a `SPOKEN_TO_SYMBOL` ordered array of `[spoken_regex, symbol]`
pairs, and a `PROTECTED_PHRASES` array of literal strings; regex compilation and
all postprocess behavior stay in Python so the JSON remains static portable
data.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

DATA_FILE = "postprocess-data.json"
SCHEMA_VERSION = 1


def _load_raw() -> dict[str, Any]:
    resource = resources.files("tuparles.data").joinpath(DATA_FILE)
    with resource.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"{DATA_FILE} must contain a JSON object")
    return data


def _string_map(data: dict[str, Any], key: str) -> dict[str, str]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"{DATA_FILE}:{key} must be an object")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise TypeError(f"{DATA_FILE}:{key} must map strings to strings")
    return dict(value)


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{DATA_FILE}:{key} must be an array of strings")
    return list(value)


def _spoken_pairs(data: dict[str, Any], key: str) -> list[tuple[str, str]]:
    value = data.get(key)
    if not isinstance(value, list):
        raise TypeError(f"{DATA_FILE}:{key} must be an ordered array")

    pairs: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            raise TypeError(f"{DATA_FILE}:{key} entries must be [spoken, symbol]")
        pairs.append((item[0], item[1]))
    return pairs


def load_postprocess_data() -> tuple[dict[str, str], list[tuple[str, str]], list[str]]:
    data = _load_raw()
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{DATA_FILE}: unsupported schema_version")
    return (
        _string_map(data, "LEXICON"),
        _spoken_pairs(data, "SPOKEN_TO_SYMBOL"),
        _string_list(data, "PROTECTED_PHRASES"),
    )


LEXICON, SPOKEN_TO_SYMBOL, PROTECTED_PHRASES = load_postprocess_data()
