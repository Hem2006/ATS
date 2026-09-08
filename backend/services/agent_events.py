"""
Stitch ATS — Agent Event Bus
In-memory pub/sub used to stream AgentStep events to SSE clients.
Not durable — durable state lives in the AgentStep table.
"""
from __future__ import annotations

import queue
from threading import Lock
from typing import Dict, List


class _RunBus:
    """
    A per-run event bus. Multiple SSE subscribers can attach to a single run;
    each subscriber gets its own queue and receives every event pushed after
    it subscribes.
    """

    def __init__(self) -> None:
        self._subscribers: List[queue.Queue] = []
        self._closed = False
        self._lock = Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
            if self._closed:
                q.put(None)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._closed = True
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(None)
            except Exception:
                pass


_buses: Dict[int, _RunBus] = {}
_buses_lock = Lock()


def get_bus(run_id: int) -> _RunBus:
    with _buses_lock:
        bus = _buses.get(run_id)
        if bus is None:
            bus = _RunBus()
            _buses[run_id] = bus
        return bus


def close_bus(run_id: int) -> None:
    with _buses_lock:
        bus = _buses.pop(run_id, None)
    if bus is not None:
        bus.close()
