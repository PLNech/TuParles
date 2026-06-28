"""Analysis engines built on the shared corpus core (features/signals/fuse).

Each engine turns the generic term features into one application:

* `dictseed` -- which terms to bias the STT decoder toward (#54).
* `keywords` -- keyphrases & tag clouds (YAKE / embedding / corpus-weight).
* `cluster`  -- semantic clusters & themes over the vocabulary.

Engines keep their heavy/optional imports (yake, sklearn, embedding backends)
lazy, so importing this package stays cheap.
"""
