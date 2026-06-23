"""Spoken-syntax families (#53). Importing this package registers every family
with the syntax core, so whatever assembles the pipeline only needs to import
`tuparles.syntax_features` once for the grammar to come alive.
"""

from tuparles.syntax_features import quotes  # noqa: F401  (import = register)
