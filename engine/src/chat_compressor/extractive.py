"""Extractive forward-channel gist: paths, headings, proper nouns, quoted labels."""

from __future__ import annotations

import re

# Shared with graph.py (PATH_FACT_RE alias). Keep both modules on this constant.
PATH_EXTENSIONS = (
    "md",
    "py",
    "ts",
    "tsx",
    "json",
    "tex",
    "sh",
    "bash",
    "zsh",
    "yaml",
    "yml",
    "toml",
    "cfg",
    "ini",
    "sql",
    "rs",
    "go",
    "java",
    "kt",
    "swift",
    "c",
    "h",
    "cpp",
    "css",
    "scss",
    "html",
    "png",
    "jpg",
    "svg",
    "pdf",
    "log.txt",
)
_PATH_EXT_ALT = "|".join(re.escape(ext) for ext in PATH_EXTENSIONS)
PATH_RE = re.compile(
    rf"(?:[\w./-]+/)*[\w.-]+\.(?:{_PATH_EXT_ALT})\b",
    re.I,
)
PATH_FACT_RE = PATH_RE
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.M)
QUOTED_RE = re.compile(r"[\"']([^\"']{2,80})[\"']")
PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
TOKEN_SPLIT_RE = re.compile(r"[^\w./#-]+")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "that",
        "this",
        "with",
        "from",
        "as",
        "at",
        "by",
        "it",
        "its",
        "into",
        "after",
        "before",
        "until",
        "while",
        "about",
        "then",
        "than",
        "so",
        "if",
        "but",
        "not",
        "no",
        "yes",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "he",
        "she",
        "his",
        "her",
        "do",
        "does",
        "did",
        "done",
        "have",
        "has",
        "had",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "just",
        "also",
        "only",
        "very",
        "more",
        "most",
        "other",
        "some",
        "such",
        "too",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "how",
        "all",
        "each",
        "few",
        "both",
        "own",
        "same",
        "any",
        "add",
        "file",
        "right",
        "left",
        "check",
        "wait",
        "call",
        "create",
        "open",
        "item",
        "list",
        "note",
        "text",
        "turn",
        "user",
        "agent",
        "please",
        "thank",
        "thanks",
    }
)


def _rank_tuple(token: str, boost: int = 0) -> tuple[int, int, int, str]:
    """Lower is better: path-ish first, then multiword, then longer."""
    lowered = token.lower()
    is_path = 0 if ("." in token and ("/" in token or any(
        lowered.endswith("." + ext) for ext in PATH_EXTENSIONS
    ))) else 1
    words = len(token.split())
    return (max(0, is_path - boost), -words, -len(token), token.lower())


def _tokenize_candidate(raw: str) -> list[str]:
    parts = [p.strip(" .,;:") for p in TOKEN_SPLIT_RE.split(raw) if p.strip(" .,;:")]
    out: list[str] = []
    for part in parts:
        if not part or part.lower() in STOPWORDS:
            continue
        if len(part) < 2:
            continue
        out.append(part)
    return out


def extractive_candidates(text: str) -> list[str]:
    """Collect ranked unique candidate strings from text."""
    if not text:
        return []
    scored: list[tuple[tuple[int, int, int, str], str]] = []
    seen: set[str] = set()

    def _add(raw: str, boost: int = 0) -> None:
        cleaned = raw.strip().strip("\"'")
        # Prefer keeping multi-word quoted / heading phrases intact.
        if " " in cleaned and 2 <= len(cleaned) <= 80:
            key = cleaned.lower()
            if key not in seen and key not in STOPWORDS:
                seen.add(key)
                scored.append((_rank_tuple(cleaned, boost=boost), cleaned))
        for tok in _tokenize_candidate(raw):
            key = tok.lower()
            if key in seen or key in STOPWORDS:
                continue
            seen.add(key)
            scored.append((_rank_tuple(tok, boost=boost), tok))

    for m in PATH_RE.finditer(text):
        _add(m.group(0), boost=2)
    for m in HEADING_RE.finditer(text):
        _add(m.group(1), boost=2)
    for m in QUOTED_RE.finditer(text):
        _add(m.group(1), boost=1)
    for m in PROPER_NOUN_RE.finditer(text):
        _add(m.group(1), boost=1)

    scored.sort(key=lambda x: x[0])
    return [tok for _, tok in scored]


def extractive_gist(text: str, max_tokens: int = 32) -> str:
    """Rank extractive tokens; return space-joined unique atomic tokens (≤ max_tokens)."""
    cands = extractive_candidates(text)
    if max_tokens < 1:
        return ""
    out: list[str] = []
    seen: set[str] = set()
    for tok in cands:
        parts = tok.split() if " " in tok else [tok]
        for part in parts:
            key = part.lower()
            if key in seen or key in STOPWORDS or len(part) < 2:
                continue
            seen.add(key)
            out.append(part)
            if len(out) >= max_tokens:
                return " ".join(out)
    return " ".join(out)


def keyword_set(text: str) -> set[str]:
    """Lowercased keyword tokens for Jaccard / recall helpers."""
    return {t.lower() for t in re.findall(r"[A-Za-z0-9_./#-]+", text) if len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0
