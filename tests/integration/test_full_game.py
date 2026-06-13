"""Full game acceptance coverage for the online room stack."""

from __future__ import annotations

import pytest

from server.engine.debt import process_auto_debt_relief
from server.engine.rules import FixedRandomSource
from server.models.game import TurnPhase
from server.room_manager import RoomManager
from server.scheduler import DeadlineConfig


def _fixed_random_source():
    return FixedRandomSource([1, 2, 2, 3, 3, 4, 4, 5])


@pytest.mark.asyncio
async def test_room_can_progress_from_creation_to_final_winner_without_real_waits():
    manager = RoomManager(
        deadline_config=DeadlineConfig(
            turn_seconds=1,
            trade_seconds=1,
            auction_seconds=1,
            disconnect_seconds=1,
        ),
        random_source_factory=_fixed_random_source,
    )

    alice = await manager.create_room("Alice")
    bob = await manager.join_room(alice.room_code, "Bob")
    carol = await manager.join_room(alice.room_code, "Carol")

    for player_id in (alice.player_id, bob.player_id, carol.player_id):
        await manager.set_ready(alice.room_code, player_id, True)
    await manager.start_game(alice.room_code, alice.player_id)

    started = await manager.get_room_state(alice.room_code)
    assert started.phase.value == "playing"
    assert started.game is not None
    assert len(started.players) == 3

    room, runtime = manager._find_room(alice.room_code)
    async with runtime.lock:
        game = room.game
        assert game is not None
        players_by_id = {player.id: player for player in room.players}

        bob_state = players_by_id[bob.player_id]
        carol_state = players_by_id[carol.player_id]
        bob_state.money = -1000
        carol_state.money = -1000

        first_bankruptcy = process_auto_debt_relief(
            game=game,
            players=room.players,
            debtor_id=bob.player_id,
        )
        assert any(event["type"] == "bankruptcy" for event in first_bankruptcy.events)
        assert game.phase != TurnPhase.GAME_OVER

        second_bankruptcy = process_auto_debt_relief(
            game=game,
            players=room.players,
            debtor_id=carol.player_id,
        )
        assert any(event["type"] == "bankruptcy" for event in second_bankruptcy.events)
        room.version += 1

    final_room = await manager.get_room_state(alice.room_code)
    assert final_room.game is not None
    assert final_room.game.phase == TurnPhase.GAME_OVER
    assert final_room.game.winner_player_id == alice.player_id
    assert [player.nickname for player in final_room.players if not player.bankrupt] == [
        "Alice"
    ]


def test_online_multiplayer_changelog_records_release_acceptance_scope():
    changelog = (
        "docs/superpowers/changelogs/2026-06-11-online-multiplayer-changelog.md"
    )
    text = __import__("pathlib").Path(changelog).read_text(encoding="utf-8")

    for phrase in [
        "完整对局",
        "Render",
        "浏览器验收",
        "旧单机入口",
        "安全边界",
    ]:
        assert phrase in text
