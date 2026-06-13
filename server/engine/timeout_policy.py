"""Deadline timeout policies for the authoritative game engine."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from server.engine.commands import EngineResult
from server.engine.debt import (
    _check_game_over,
    _execute_bankruptcy_without_creditor,
    process_auto_debt_relief,
)
from server.engine.rules import RandomSource, _advance_turn, apply_command
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState
from server.protocol import CommandName


def _find_player(players: list[PlayerState], player_id: UUID) -> PlayerState | None:
    for player in players:
        if player.id == player_id:
            return player
    return None


def _find_player_by_seat(players: list[PlayerState], seat: int) -> PlayerState | None:
    for player in players:
        if player.seat == seat and not player.bankrupt:
            return player
    return None


def _with_event(result: EngineResult, event: dict) -> EngineResult:
    result.events.insert(0, event)
    return result


def apply_phase_timeout(
    game: GameState,
    players: list[PlayerState],
    *,
    random_source: RandomSource,
    now: datetime,
) -> EngineResult:
    """Apply the default timeout behavior for the game's active phase."""

    if game.phase == TurnPhase.WAITING_FOR_ROLL:
        game.trade_window_available = False
        result = apply_command(
            game=game,
            actor_id=game.current_player_id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=random_source,
            now=now,
            players=players,
        )
        return _with_event(result, {"type": "turn_timeout", "playerId": str(game.current_player_id)})

    if game.phase == TurnPhase.AWAITING_PROPERTY_DECISION:
        result = apply_command(
            game=game,
            actor_id=game.current_player_id,
            command=CommandName.DECLINE_PROPERTY,
            payload={},
            random_source=random_source,
            now=now,
            players=players,
        )
        return _with_event(result, {"type": "property_decision_timeout", "playerId": str(game.current_player_id)})

    if game.phase == TurnPhase.AWAITING_CARD_DECISION:
        player = _find_player(players, game.current_player_id)
        if player is None:
            return EngineResult(changed=False)
        pending_type = None
        if isinstance(game.pending_decision, dict):
            pending_type = game.pending_decision.get("type")
        if pending_type == "teleport_decision":
            player.position = 20
            game.pending_decision = None
            _advance_turn(game, players, player.id, False)
            return EngineResult(
                changed=True,
                events=[
                    {"type": "card_decision_timeout", "playerId": str(player.id)},
                    {"type": "teleport_defaulted", "playerId": str(player.id), "position": 20},
                ],
            )
        return EngineResult(changed=False)

    if game.phase == TurnPhase.AUCTION and game.auction is not None:
        bidder = _find_player_by_seat(players, game.auction.current_bidder_seat)
        if bidder is None:
            return EngineResult(changed=False)
        result = apply_command(
            game=game,
            actor_id=bidder.id,
            command=CommandName.PASS_AUCTION,
            payload={},
            random_source=random_source,
            now=now,
            players=players,
        )
        return _with_event(result, {"type": "auction_timeout", "playerId": str(bidder.id)})

    if game.phase == TurnPhase.TRADE_NEGOTIATION and game.trade is not None:
        responder_id = game.trade.current_responder
        if responder_id is None:
            return EngineResult(changed=False)
        result = apply_command(
            game=game,
            actor_id=responder_id,
            command=CommandName.REJECT_TRADE,
            payload={},
            random_source=random_source,
            now=now,
            players=players,
        )
        return _with_event(result, {"type": "trade_timeout", "playerId": str(responder_id)})

    if game.phase == TurnPhase.DEBT_RELIEF and game.debt is not None:
        debt = game.debt
        result = process_auto_debt_relief(
            game=game,
            players=players,
            debtor_id=debt.player_id,
            creditor_id=debt.creditor_id,
        )
        return _with_event(result, {"type": "debt_timeout", "playerId": str(debt.player_id)})

    return EngineResult(changed=False)


def apply_disconnect_timeout(
    game: GameState,
    players: list[PlayerState],
    *,
    player_id: UUID,
) -> EngineResult:
    """Force a disconnected player into no-creditor bankruptcy."""

    player = _find_player(players, player_id)
    if player is None or player.bankrupt:
        return EngineResult(changed=False)

    if game.trade is not None:
        trade_player_ids = {game.trade.initiator_id, game.trade.target_id}
        if player_id in trade_player_ids:
            game.trade = None
            game.trade_window_available = False
            game.phase = TurnPhase.WAITING_FOR_ROLL

    events = [
        {"type": "disconnect_timeout", "playerId": str(player_id)},
        *_execute_bankruptcy_without_creditor(game, players, player),
    ]
    _check_game_over(game, players)
    return EngineResult(changed=True, events=events)
