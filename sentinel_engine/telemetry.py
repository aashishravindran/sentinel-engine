# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Per-layer latency, recorded only while a caller is collecting.

Wrap a request in ``collect_timings()`` to get seconds spent per layer, e.g.
``{"identity": 0.0012, "kb": 0.0841, "postfilter": 0.00002}``. Outside that
block ``timed()`` costs one context-variable lookup.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

_timings: ContextVar[dict[str, float] | None] = ContextVar("sentinel_timings", default=None)


@contextmanager
def collect_timings() -> Generator[dict[str, float]]:
    timings: dict[str, float] = {}
    token = _timings.set(timings)
    try:
        yield timings
    finally:
        _timings.reset(token)


@contextmanager
def timed(layer: str) -> Generator[None]:
    timings = _timings.get()
    if timings is None:
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[layer] = timings.get(layer, 0.0) + time.perf_counter() - start
