"""JSON responses that survive a non-finite float.

Starlette renders with ``allow_nan=False``, so a single ``NaN`` or
``Infinity`` anywhere in a payload raises ``ValueError: Out of range float
values are not JSON compliant`` — at *render* time, after the route has
already done its work — and the endpoint returns 500.

That happened in production on 2026-09-23: ``/signals/``,
``/watchlist/signals``, ``/ai-desk/today`` and ``/market/performance`` all
failed together, 32 times in a day, because they serialise the same computed
numbers.

Non-finite values reach us from two directions: arithmetic upstream (an
``inf - inf``, a ratio against a zero baseline), and Postgres, where ``NaN``
is a legal value for ``double precision`` and comes back as ``float('nan')``.

The fix replaces them with ``null``, which every consumer of these fields
already handles — they are all optional — and **logs the path of each one**,
so the underlying cause stays visible rather than being quietly papered
over. Grep the logs for ``non-finite`` to find where they come from.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Enough to identify the culprit without filling the log with one bad row.
_MAX_REPORTED = 5


def scrub_non_finite(value: Any, path: str = "$") -> tuple[Any, list[str]]:
    """``value`` with NaN/±Infinity replaced by ``None``, and where they were.

    Returns ``(cleaned, paths)``; ``paths`` is empty when nothing changed.
    """
    # bool is an int, not a float, so it never reaches the isfinite check.
    if isinstance(value, float):
        if math.isfinite(value):
            return value, []
        return None, [f"{path}={value!r}"]
    if isinstance(value, dict):
        cleaned_map: dict[Any, Any] = {}
        found: list[str] = []
        for key, item in value.items():
            cleaned_map[key], hits = scrub_non_finite(item, f"{path}.{key}")
            found += hits
        return cleaned_map, found
    if isinstance(value, (list, tuple)):
        cleaned_seq: list[Any] = []
        found = []
        for index, item in enumerate(value):
            cleaned_item, hits = scrub_non_finite(item, f"{path}[{index}]")
            cleaned_seq.append(cleaned_item)
            found += hits
        return cleaned_seq, found
    return value, []


class SafeJSONResponse(JSONResponse):
    """``JSONResponse`` that turns a non-finite float into ``null``.

    The common path is untouched: rendering is tried first and only a failure
    triggers the walk, so responses that are already valid pay nothing for
    this. A ``ValueError`` from anything other than a non-finite float still
    surfaces — the second render raises it again.
    """

    def render(self, content: Any) -> bytes:
        try:
            return super().render(content)
        except ValueError:
            cleaned, found = scrub_non_finite(content)
            if not found:
                raise  # not our problem; let the real error through
            extra = "" if len(found) <= _MAX_REPORTED else f" (+{len(found) - _MAX_REPORTED} more)"
            logger.warning(
                "Replaced %d non-finite float(s) with null: %s%s",
                len(found),
                ", ".join(found[:_MAX_REPORTED]),
                extra,
            )
            return super().render(cleaned)
