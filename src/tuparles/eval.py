"""Scoring for the code-switch eval harness.

Two signals, by deliberate design (see docs/research/2026-06-23-codeswitch-eval.md):

* **Slot checks — the gate.** Each corpus case declares the tokens that MUST
  survive the decode (the homophone target: "fan out") and the misfires that
  must NOT appear ("fais un air"). A case passes iff every `must_contain`
  phrase is present *and* no `must_not_contain` phrase is. This is the only
  pass/fail signal, because the adversarial point is specific words, not whole
  sentences — and because exact transcript equality is the wrong bar for ASR.

* **WER — the trend.** Word error rate against the reference transcript,
  reported but never a gate: a harmless rewording ("c'est" vs "c est") should
  move the number without failing the case. It tells us whether decoding is
  drifting overall, between releases or models.

Dependency-free on purpose: a small word-level Levenshtein and an NFC +
casefold + de-punctuate normalize. Slot matching is on *contiguous token
sublists*, not raw substrings, so "fan out" can't spuriously match inside
"fanfan outil".
"""

import re
import unicodedata
from dataclasses import dataclass

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, NFC, strip punctuation, collapse whitespace.

    Apostrophes and hyphens become spaces so "fan-out"/"fan out" and
    "c'est"/"c est" compare equal — the spelling of the seam is not what we
    are testing.
    """
    text = unicodedata.normalize("NFC", text).casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    norm = normalize(text)
    return norm.split() if norm else []


def contains_phrase(haystack: list[str], needle: list[str]) -> bool:
    """True if `needle` appears as a contiguous run of tokens in `haystack`."""
    if not needle:
        return True
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate: word-level edit distance / reference length.

    1.0 when the reference is non-empty and nothing matches; 0.0 for two empty
    strings; capped only implicitly (insertions can push it above 1.0, which
    is correct — a hallucinated outro is worse than a deletion).
    """
    ref = tokens(reference)
    hyp = tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cost = 0 if r == h else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1] / len(ref)


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    missing: list[str]  # must_contain phrases not found
    leaked: list[str]  # must_not_contain phrases found
    wer: float
    hypothesis: str

    def summary(self) -> str:
        bits = []
        if self.missing:
            bits.append(f"missing {self.missing}")
        if self.leaked:
            bits.append(f"LEAKED {self.leaked}")
        verdict = "PASS" if self.passed else "FAIL"
        detail = f" ({'; '.join(bits)})" if bits else ""
        return f"{verdict} {self.case_id} wer={self.wer:.2f}{detail}"


def score_case(case: dict, hypothesis: str) -> CaseResult:
    """Score one decoded hypothesis against a corpus case."""
    hyp = tokens(hypothesis)
    missing = [
        phrase
        for phrase in case.get("must_contain", [])
        if not contains_phrase(hyp, tokens(phrase))
    ]
    leaked = [
        phrase
        for phrase in case.get("must_not_contain", [])
        if contains_phrase(hyp, tokens(phrase))
    ]
    return CaseResult(
        case_id=case["id"],
        passed=not missing and not leaked,
        missing=missing,
        leaked=leaked,
        wer=wer(case["text"], hypothesis),
        hypothesis=hypothesis,
    )
