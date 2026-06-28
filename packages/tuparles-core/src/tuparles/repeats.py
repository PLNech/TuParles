"""Collapse ASR repetition loops.

Whisper occasionally locks onto a phrase at the end of a take (outro
music, trailing silence) and emits it in a loop: "DIPI. DIPI. DIPI. DIPI."
Real speech repeats a full sentence twice for emphasis — almost never
three times verbatim. So: runs of 3+ identical sentences collapse to one;
doubles survive untouched.
"""

import re

# Split after sentence enders, capturing the separator so newlines and
# spacing survive reconstruction.
_SENTENCE_SEP = re.compile(r"((?<=[.?!…])\s+)")

_RUN_THRESHOLD = 3


def collapse_repeats(text: str) -> str:
    parts = _SENTENCE_SEP.split(text)
    sentences = parts[0::2]
    seps = parts[1::2] + [""]

    # Group consecutive identical sentences (whitespace/case-insensitive).
    groups: list[list] = []  # [first_sentence, first_sep, count, last_sep]
    for sentence, sep in zip(sentences, seps, strict=False):
        key = sentence.strip().casefold()
        if groups and key and groups[-1][0].strip().casefold() == key:
            groups[-1][2] += 1
            groups[-1][3] = sep
        else:
            groups.append([sentence, sep, 1, sep])

    out: list[str] = []
    for sentence, first_sep, count, last_sep in groups:
        if count >= _RUN_THRESHOLD:
            out.append(sentence + last_sep)  # one survivor, original spacing
        else:
            out.extend([sentence + first_sep] * (count - 1))
            out.append(sentence + last_sep)
    return "".join(out)
