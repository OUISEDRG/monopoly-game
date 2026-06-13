"""Room deadline scheduler.

The scheduler is intentionally small: tests can call ``run_once`` with an
injected clock, while the FastAPI app can run it as a background task.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.room_manager import RoomManager, TimeoutResult


@dataclass(frozen=True, slots=True)
class DeadlineConfig:
    """Per-room timeout durations in seconds."""

    turn_seconds: float = 90
    trade_seconds: float = 45
    auction_seconds: float = 30
    disconnect_seconds: float = 300
    minimum_restored_turn_seconds: float = 15


class RoomScheduler:
    """Periodic driver for RoomManager deadline processing."""

    def __init__(self, manager: RoomManager, *, poll_interval: float = 0.5) -> None:
        self._manager = manager
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self) -> list[TimeoutResult]:
        return await self._manager.process_due_timeouts()

    async def _run(self) -> None:
        while not self._stopped.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass
