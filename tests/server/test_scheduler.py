"""Scheduler and timeout policy tests for online rooms."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from server.engine.rules import FixedRandomSource
from server.protocol import CommandName
from server.room_manager import RoomManager
from server.scheduler import DeadlineConfig


class ManualClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 6, 13, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


async def _setup_started_room(manager: RoomManager):
    host = await manager.create_room("Alice")
    guest = await manager.join_room(host.room_code, "Bob")
    await manager.set_ready(host.room_code, host.player_id, True)
    await manager.set_ready(host.room_code, guest.player_id, True)
    room = await manager.start_game(host.room_code, host.player_id)
    return host, guest, room


@pytest.mark.asyncio
async def test_start_game_sets_turn_deadline_from_injected_clock():
    clock = ManualClock()
    manager = RoomManager(
        deadline_config=DeadlineConfig(turn_seconds=3),
        clock=clock.now,
    )

    _, _, room = await _setup_started_room(manager)

    assert room.game is not None
    assert room.game.turn_deadline == clock.now() + timedelta(seconds=3)


@pytest.mark.asyncio
async def test_turn_timeout_auto_rolls_without_real_waiting():
    clock = ManualClock()
    manager = RoomManager(
        deadline_config=DeadlineConfig(turn_seconds=1),
        clock=clock.now,
        random_source_factory=lambda: FixedRandomSource([1, 2]),
    )
    host, _, room = await _setup_started_room(manager)
    initial_version = room.version

    clock.advance(seconds=1.1)
    results = await manager.process_due_timeouts()

    room = await manager.get_room_state(host.room_code)
    assert room.version == initial_version + 1
    assert room.game is not None
    assert room.game.last_dice == (1, 2)
    assert any(event["type"] == "turn_timeout" for result in results for event in result.events)


@pytest.mark.asyncio
async def test_trade_timeout_rejects_trade_and_restores_turn_timer():
    clock = ManualClock()
    manager = RoomManager(
        deadline_config=DeadlineConfig(turn_seconds=10, trade_seconds=2),
        clock=clock.now,
    )
    host, guest, room = await _setup_started_room(manager)

    version, _, _ = await manager.execute_game_command(
        code=host.room_code,
        player_id=host.player_id,
        request_id=uuid4(),
        room_version=room.version,
        command=CommandName.PROPOSE_TRADE,
        payload={
            "targetId": str(guest.player_id),
            "initiatorOffer": {"properties": [], "cash": 100, "jailFreeCard": False},
            "targetOffer": {"properties": [], "cash": 0, "jailFreeCard": False},
        },
    )
    room = await manager.get_room_state(host.room_code)
    assert room.version == version
    assert room.game is not None
    assert room.game.trade is not None
    assert room.game.trade.deadline == clock.now() + timedelta(seconds=2)
    assert room.game.turn_deadline is None

    clock.advance(seconds=2.1)
    results = await manager.process_due_timeouts()

    room = await manager.get_room_state(host.room_code)
    assert room.game is not None
    assert room.game.trade is None
    assert room.game.trade_window_available is False
    assert room.game.turn_deadline == clock.now() + timedelta(seconds=10)
    assert any(event["type"] == "trade_timeout" for result in results for event in result.events)


@pytest.mark.asyncio
async def test_disconnect_timeout_bankrupts_player_without_creditor():
    clock = ManualClock()
    manager = RoomManager(
        deadline_config=DeadlineConfig(disconnect_seconds=5),
        clock=clock.now,
    )
    host, _, room = await _setup_started_room(manager)

    live_room, runtime = manager._find_room(host.room_code)
    async with runtime.lock:
        assert live_room.game is not None
        player = next(p for p in live_room.players if p.id == host.player_id)
        player.properties.append(1)
        live_room.game.property_owners[1] = host.player_id

    await manager.disconnect(host.room_code, host.player_id)
    clock.advance(seconds=5.1)
    results = await manager.process_due_timeouts()

    room = await manager.get_room_state(host.room_code)
    assert room.game is not None
    player = next(p for p in room.players if p.id == host.player_id)
    assert player.bankrupt is True
    assert 1 not in player.properties
    assert room.game.auction is not None
    assert room.game.auction.position == 1
    assert any(
        event["type"] == "disconnect_timeout"
        for result in results
        for event in result.events
    )
