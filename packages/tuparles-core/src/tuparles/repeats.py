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


# --- word-level loop guard (#54, offline `transcribe`) -----------------------
#
# collapse_repeats needs sentence enders; a decode loop on near-silence often
# has none ("the the the …", or one phrase looping across 30 s). This works on
# word tokens instead and is deliberately MORE conservative than the 3-sentence
# rule above, because a meeting transcript is a record, not a dictation: only a
# phrase repeated verbatim LOOP_MIN_COPIES times in a row, covering at least
# LOOP_MIN_WORDS words, is a loop. So a one-word loop needs 12 copies, a
# two-word one 6, three words or more 4. "non non non", "très très très
# très", a chanted "on y va" x3 and "Thank you." x4 all stay untouched.
LOOP_MAX_PHRASE_WORDS = 16  # Whisper loops one short sentence, not a paragraph
LOOP_MIN_COPIES = 4  # three verbatim copies is still something people say
LOOP_MIN_WORDS = 12  # copies x phrase length: protects short honest repeats

_NON_WORD = re.compile(r"[^\w']+")


def _norm(token: str) -> str:
    """Case- and punctuation-blind token key: "You." == "you!" == "YOU"."""
    return _NON_WORD.sub("", token.casefold())


def _copies(keys: list[str], start: int, k: int) -> int:
    phrase = keys[start : start + k]
    r = 1
    while keys[start + r * k : start + (r + 1) * k] == phrase:
        r += 1
    return r


def find_loop(tokens: list[str], start: int = 0) -> tuple[int, int, int] | None:
    """The first decode loop at or after `start`: (index, phrase_len, copies),
    or None. Earliest index wins, then the shortest phrase (the true period:
    "la la la la" is "la" x4, not "la la" x2). Pure, never raises."""
    keys = [_norm(t) for t in tokens]
    n = len(keys)
    for i in range(start, n):
        if not keys[i]:
            continue  # a bare punctuation token never opens a loop
        for k in range(1, min(LOOP_MAX_PHRASE_WORDS, (n - i) // 2) + 1):
            r = _copies(keys, i, k)
            if r >= LOOP_MIN_COPIES and r * k >= LOOP_MIN_WORDS:
                return i, k, r
    return None


def cut_loops(tokens: list[str]) -> tuple[list[int], list[tuple[int, int, int]]]:
    """Keep ONE copy of every loop `find_loop` reports and drop the rest, plus
    a trailing partial copy (the decode usually stops mid-phrase). Text after
    the loop is kept: on a real hallucination there is none, and on a false
    positive that is strictly less destructive than cutting the tail.

    Returns (kept token indices, loops as (index, phrase_len, copies)), so a
    caller can carry word timings across. Untouched input → all indices, []."""
    keys = [_norm(t) for t in tokens]
    kept: list[int] = []
    loops: list[tuple[int, int, int]] = []
    pos = 0
    while True:
        hit = find_loop(tokens, pos)
        if hit is None:
            kept.extend(range(pos, len(tokens)))
            return kept, loops
        i, k, r = hit
        kept.extend(range(pos, i + k))  # everything before + the first copy
        pos = i + k * r
        tail = 0  # a partial copy right after the run is the loop, cut short
        while (
            tail < k - 1
            and pos + tail < len(keys)
            and keys[pos + tail] == keys[i + tail]
        ):
            tail += 1
        pos += tail
        loops.append((i, k, r))
