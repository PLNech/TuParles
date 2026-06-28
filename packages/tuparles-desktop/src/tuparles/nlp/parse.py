"""Turn a source file into a stream of *typed, weighted* vocabulary terms.

The premise of dict-seeding (#54): the words you dictate at your machine are
the words that live in your code. Whisper mangles them ("RequestOptions" ->
"request options", "faceting" -> "facetting") because they are out-of-vocab.
If we mine the corpus, we can bias the decoder toward them.

But not every word is worth the same. A dependency name in `package.json` is a
near-certain dictation target; a word buried in a comment is a maybe. So every
term carries a `SrcType` recording *where structurally* it was found, and each
SrcType has a weight. That hierarchy is the "semantic weighting" -- it is the
whole point, so it lives here as one readable table.

Python and Markdown get real AST treatment (we know a def name from a call,
an H1 from prose). Other languages (the C++ in AlgoliaSaaS, JS, Go...) get a
coarse identifier+comment sweep -- tree-sitter would upgrade them to true
hierarchy, noted as the obvious next step but YAGNI for a first pass.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
import tomllib
from collections.abc import Iterator
from enum import Enum

from tuparles.nlp.crawl import Kind, SourceFile


class SrcType(str, Enum):
    """Where a term was found -- the structural provenance that sets its weight."""

    DEP = "dep"  # a declared dependency name (the strongest signal)
    DEF_NAME = "def_name"  # a class / function / module *definition* identifier
    IMPORT = "import"  # an imported module/package name
    IDENT = "ident"  # an identifier *used* (call, attribute, name ref)
    CODE_IDENT = "code_ident"  # identifier from a non-AST language (coarse)
    DOCSTRING = "docstring"  # a word inside a docstring
    COMMENT = "comment"  # a word inside a comment
    MD_H1 = "md_h1"
    MD_H2 = "md_h2"
    MD_H3 = "md_h3"
    MD_HX = "md_hx"  # H4 and deeper
    MD_CODE_INLINE = "md_code_inline"  # `inline code` in prose
    MD_CODE_FENCE = "md_code_fence"  # fenced block content
    MD_PROSE = "md_prose"  # ordinary Markdown prose
    TEXT = "text"  # fallback plain text


# The hierarchy, in one place. Higher = more likely a real dictation target.
WEIGHT: dict[SrcType, float] = {
    SrcType.DEP: 10.0,
    SrcType.DEF_NAME: 6.0,
    SrcType.MD_H1: 5.0,
    SrcType.MD_H2: 4.0,
    SrcType.IMPORT: 4.0,
    SrcType.MD_H3: 3.0,
    SrcType.IDENT: 3.0,
    SrcType.MD_CODE_INLINE: 3.0,
    SrcType.MD_HX: 2.5,
    SrcType.CODE_IDENT: 2.0,
    SrcType.MD_CODE_FENCE: 2.0,
    SrcType.DOCSTRING: 1.5,
    SrcType.MD_PROSE: 1.0,
    SrcType.COMMENT: 1.0,
    SrcType.TEXT: 0.5,
}

# Identifier srctypes (vs natural-language words) -- used for the whisper-risk
# metafeature: code identifiers are exactly what an STT model has never seen.
IDENTIFIER_TYPES = frozenset(
    {SrcType.DEF_NAME, SrcType.IMPORT, SrcType.IDENT, SrcType.CODE_IDENT}
)

# A "word" for prose: letters (incl. French accents) then letters/digits/_/-.
# We keep the original case; aggregation casefolds the key, keeps the surface.
_WORD = re.compile(r"[A-Za-zÀ-ſ][A-Za-zÀ-ſ0-9_-]+")
# A bare identifier in non-AST code: a leading letter/underscore then word chars.
_CODE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
# Comment scrapers for the coarse path.
_LINE_COMMENT = re.compile(r"(?://|#)\s?(.*)$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)


def _words(text: str) -> Iterator[str]:
    for m in _WORD.finditer(text):
        yield m.group(0)


# --------------------------------------------------------------------------- #
# Python: real AST -- we can tell a definition from a use, and read docstrings #
# --------------------------------------------------------------------------- #
def parse_python(src: str) -> Iterator[tuple[str, SrcType]]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return  # not valid py3 (py2 file, template) -- skip, don't guess

    module_doc = ast.get_docstring(tree)
    if module_doc:
        for w in _words(module_doc):
            yield w, SrcType.DOCSTRING

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node.name, SrcType.DEF_NAME
            doc = ast.get_docstring(node)
            if doc:
                for w in _words(doc):
                    yield w, SrcType.DOCSTRING
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], SrcType.IMPORT
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module.split(".")[0], SrcType.IMPORT
        elif isinstance(node, ast.Name):
            yield node.id, SrcType.IDENT
        elif isinstance(node, ast.Attribute):
            yield node.attr, SrcType.IDENT

    # Comments aren't in the AST -- tokenize for them, best-effort.
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                for w in _words(tok.string):
                    yield w, SrcType.COMMENT
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass


# --------------------------------------------------------------------------- #
# Markdown: heading hierarchy + code spans, via markdown-it token stream       #
# --------------------------------------------------------------------------- #
_HEADING_TYPE = {1: SrcType.MD_H1, 2: SrcType.MD_H2, 3: SrcType.MD_H3}


def parse_markdown(src: str) -> Iterator[tuple[str, SrcType]]:
    from markdown_it import MarkdownIt

    tokens = MarkdownIt("commonmark").parse(src)
    pending_heading: SrcType | None = None
    for tok in tokens:
        if tok.type == "heading_open":
            level = int(tok.tag[1:])  # "h2" -> 2
            pending_heading = _HEADING_TYPE.get(level, SrcType.MD_HX)
        elif tok.type == "heading_close":
            pending_heading = None
        elif tok.type == "fence" or tok.type == "code_block":
            # The fenced code itself -- identifiers a dev would dictate.
            for m in _CODE_IDENT.finditer(tok.content):
                yield m.group(0), SrcType.MD_CODE_FENCE
        elif tok.type == "inline":
            if pending_heading is not None:
                for w in _words(tok.content):
                    yield w, pending_heading
            else:
                for child in tok.children or ():
                    if child.type == "code_inline":
                        for m in _CODE_IDENT.finditer(child.content):
                            yield m.group(0), SrcType.MD_CODE_INLINE
                    elif child.type == "text":
                        for w in _words(child.content):
                            yield w, SrcType.MD_PROSE


# --------------------------------------------------------------------------- #
# Manifests: dependency names get the top weight (user's explicit ask)         #
# --------------------------------------------------------------------------- #
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def parse_manifest(src: str, name: str) -> Iterator[tuple[str, SrcType]]:
    name = name.lower()
    try:
        if name == "pyproject.toml":
            data = tomllib.loads(src)
            yield from _pyproject_deps(data)
        elif name == "package.json":
            data = json.loads(src)
            for field in (
                "dependencies",
                "devDependencies",
                "peerDependencies",
                "optionalDependencies",
            ):
                for dep in data.get(field) or {}:
                    yield dep, SrcType.DEP
        elif name.startswith("requirements") and name.endswith(".txt"):
            for line in src.splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                m = _REQ_NAME.match(line)
                if m:
                    yield m.group(1), SrcType.DEP
        elif name == "go.mod":
            for line in src.splitlines():
                line = line.strip()
                if line.startswith(("require", "module", "//", "go ", ")", "(")):
                    continue
                parts = line.split()
                if parts:
                    yield parts[0].rstrip("/").split("/")[-1], SrcType.DEP
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, ValueError):
        return


def _pyproject_deps(data: dict) -> Iterator[tuple[str, SrcType]]:
    project = data.get("project", {})
    for dep in project.get("dependencies", []) or []:
        m = _REQ_NAME.match(str(dep))
        if m:
            yield m.group(1), SrcType.DEP
    poetry = data.get("tool", {}).get("poetry", {})
    for dep in poetry.get("dependencies", {}):
        if dep.lower() != "python":
            yield dep, SrcType.DEP
    for group in poetry.get("group", {}).values():
        for dep in group.get("dependencies", {}) or {}:
            if dep.lower() != "python":
                yield dep, SrcType.DEP


# --------------------------------------------------------------------------- #
# Other code (C++, JS, Go, ...): coarse identifier + comment sweep             #
# --------------------------------------------------------------------------- #
def parse_code_coarse(src: str) -> Iterator[tuple[str, SrcType]]:
    """No AST -- we can't tell a def from a use, so everything is CODE_IDENT.

    tree-sitter would give real hierarchy here; deferred (YAGNI for v1).
    """
    body = src
    for m in _BLOCK_COMMENT.finditer(src):
        for w in _words(m.group(1)):
            yield w, SrcType.COMMENT
    body = _BLOCK_COMMENT.sub(" ", body)
    for m in _LINE_COMMENT.finditer(body):
        for w in _words(m.group(1)):
            yield w, SrcType.COMMENT
    code_only = _LINE_COMMENT.sub("", body)
    for m in _CODE_IDENT.finditer(code_only):
        yield m.group(0), SrcType.CODE_IDENT


def parse_text(text: str) -> Iterator[tuple[str, SrcType]]:
    """Plain prose (chat messages, logs, journal entries) -> TEXT-weighted words.

    The modular escape hatch: any corpus that isn't code -- our dictation
    history, a meeting transcript, a logfile -- can be mined as flat prose and
    still flow through features / signals / engines.
    """
    for m in _WORD.finditer(text):
        yield m.group(0), SrcType.TEXT


def parse_file(sf: SourceFile, text: str) -> Iterator[tuple[str, SrcType]]:
    """Dispatch a file to its parser by kind."""
    if sf.kind is Kind.PYTHON:
        yield from parse_python(text)
    elif sf.kind is Kind.MARKDOWN:
        yield from parse_markdown(text)
    elif sf.kind is Kind.MANIFEST:
        yield from parse_manifest(text, sf.abspath.name)
    elif sf.kind is Kind.CODE:
        yield from parse_code_coarse(text)
