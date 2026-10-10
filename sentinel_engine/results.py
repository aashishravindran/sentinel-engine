# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Turning authorized chunks into a tool result. Identical across adapters."""

from collections.abc import Iterable

from sentinel_engine.base import Chunk

# Below this cosine similarity, the caller's permitted documents do not cover
# the query. Returning a clear "no access" message beats feeding the model
# low-signal text it will hallucinate around.
DEFAULT_MIN_RELEVANCE_SCORE = 0.25

NO_RELEVANT_ACCESS = (
    "You do not have access to documents relevant to this query. "
    "The information may exist but is not within your permitted scope."
)
ACCESS_DENIED = "Access denied."


def filter_relevant(
    chunks: Iterable[Chunk], min_score: float = DEFAULT_MIN_RELEVANCE_SCORE
) -> list[Chunk]:
    return [c for c in chunks if c["score"] >= min_score]


def format_results(chunks: list[Chunk]) -> str:
    if not chunks:
        return NO_RELEVANT_ACCESS
    blocks: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk["metadata"].get("title", "")
        header = f"[{i}] {title}" if title else f"[{i}]"
        blocks.append(f"{header} (score: {chunk['score']})\n{chunk['text']}")
    return "\n\n---\n\n".join(blocks)
