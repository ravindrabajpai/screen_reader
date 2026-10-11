"""Dependency-free sentence-aware chunks for progressive speech."""

from __future__ import annotations

import re
from collections import deque

FIRST_WORDS = 60
LATER_WORDS = 190
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e"}


def normalize_text(text: str) -> str:
    """Preserve blank-line paragraph breaks; join wrapped lines within paragraphs."""
    paragraphs = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n\n".join(part for p in paragraphs if (part := " ".join(p.split())))


def sentences(paragraph: str) -> list[str]:
    result = []
    start = 0
    for match in re.finditer(r'''[.!?]+["'’”\)\]]*(?:\s+|$)''', paragraph):
        punctuation = match.start()
        if paragraph[punctuation] == ".":
            token = re.search(r"([\w.]+)$", paragraph[:punctuation])
            word = token.group(1) if token else ""
            if word.lower() in ABBREVIATIONS or re.fullmatch(r"(?:[A-Za-z]\.)*[A-Za-z]", word):
                continue
        result.append(paragraph[start:match.end()].strip())
        start = match.end()
    if paragraph[start:].strip():
        result.append(paragraph[start:].strip())
    return result


def _split_long(text: str, limit: int) -> tuple[str, str]:
    words = text.split()
    if len(words) <= limit:
        return text, ""
    # Prefer a substantial phrase, avoiding tiny fragments at early punctuation.
    minimum = max(1, limit // 2)
    for punctuation in (";:—", ","):
        candidates = [i for i in range(minimum, limit + 1) if words[i - 1].rstrip('"\'’”)]').endswith(tuple(punctuation))]
        if candidates:
            limit = candidates[-1]
            break
    return " ".join(words[:limit]), " ".join(words[limit:])


def chunk_text(text: str) -> list[str]:
    """Keep text in order with a small first chunk and bounded later chunks."""
    normalized = normalize_text(text)
    units = deque((sentence, index) for index, paragraph in enumerate(normalized.split("\n\n")) for sentence in sentences(paragraph))
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    paragraph_id = None
    while units:
        limit = FIRST_WORDS if not chunks else LATER_WORDS
        target = 2 if not chunks else 8
        maximum = 3 if not chunks else 10
        sentence, paragraph = units[0]
        word_count = len(sentence.split())
        if current and (count + word_count > limit or len(current) >= maximum or (paragraph != paragraph_id and len(current) >= target)):
            chunks.append(" ".join(current))
            current, count = [], 0
            continue
        if not current and word_count > limit:
            part, remainder = _split_long(sentence, limit)
            chunks.append(part)
            units[0] = (remainder, paragraph)
            continue
        units.popleft()
        current.append(sentence)
        count += word_count
        paragraph_id = paragraph
    if current:
        chunks.append(" ".join(current))
    return chunks
