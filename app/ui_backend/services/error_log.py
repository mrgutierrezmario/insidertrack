"""
A tiny in-process record of unhandled exceptions, so an operator can see
"anything blow up today?" from /health and the daily admin email instead
of reading container logs. Bounded; resets on restart (the log still has
everything).
"""

import threading
from collections import deque
from datetime import datetime, timezone

_MAX = 200
_lock = threading.Lock()
_events: deque = deque(maxlen=_MAX)


def record(kind: str, where: str, rid: str = "") -> None:
    with _lock:
        _events.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "type": kind, "where": where, "rid": rid})


def summary(hours: int = 24) -> dict:
    """{count, by_type: {...}, latest: [...]} for the last `hours`."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with _lock:
        recent = [e for e in _events if e["at"] >= cutoff]
    by_type: dict[str, int] = {}
    for e in recent:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    return {"hours": hours, "count": len(recent), "by_type": by_type, "latest": recent[-5:]}
