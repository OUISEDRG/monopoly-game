"""房间状态模型、房间阶段枚举和公共快照构造器。

对应设计规范第 8 节。RoomRuntime（锁、WebSocket、请求缓存、
计时任务）不进入 RoomState 或公共快照。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID

from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState


class RoomPhase(str, Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    FINISHED = "finished"


@dataclass(slots=True)
class RoomState:
    code: str
    host_player_id: UUID
    phase: RoomPhase = RoomPhase.LOBBY
    players: list[PlayerState] = field(default_factory=list)
    game: GameState | None = None
    version: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now())
    last_nonempty_at: datetime = field(default_factory=lambda: datetime.now())


def _convert_value(val: object) -> object:
    """递归转换 UUID、Enum、datetime、tuple 为 JSON 可序列化值。"""
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, Enum):
        return val.value
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, tuple):
        return [_convert_value(v) for v in val]
    if isinstance(val, list):
        return [_convert_value(v) for v in val]
    if isinstance(val, dict):
        return {str(k): _convert_value(v) for k, v in val.items()}
    if isinstance(val, set):
        return [_convert_value(v) for v in val]
    return val


def _player_to_dict(player: PlayerState) -> dict:
    return {
        "id": str(player.id),
        "nickname": player.nickname,
        "seat": player.seat,
        "color": player.color,
        "ready": player.ready,
        "connected": player.connected,
        "disconnectedAt": player.disconnected_at.isoformat() if player.disconnected_at else None,
        "bankrupt": player.bankrupt,
        "money": player.money,
        "position": player.position,
        "properties": player.properties,
        "inJail": player.in_jail,
        "jailTurns": player.jail_turns,
        "hasGetOutOfJailCard": player.has_get_out_of_jail_card,
        "consecutiveDoubles": player.consecutive_doubles,
    }


def _debt_to_dict(debt: object) -> dict:
    """DebtState → dict，显式排除 restore_callback (Callable)。"""
    from server.engine.debt import DebtState
    d = debt  # type: DebtState
    return {
        "playerId": str(d.player_id),
        "creditorId": str(d.creditor_id) if d.creditor_id is not None else None,
        "owedAmount": d.owed_amount,
        "deadline": d.deadline.isoformat() if d.deadline is not None else None,
        "completed": d.completed,
    }


def _auction_to_dict(auction: object) -> dict:
    """AuctionState → dict，set 转 list。"""
    from server.engine.auction import AuctionState
    a = auction  # type: AuctionState
    return {
        "position": a.position,
        "startingPrice": a.starting_price,
        "highestBid": a.highest_bid,
        "highestBidderId": str(a.highest_bidder_id) if a.highest_bidder_id is not None else None,
        "currentBidderSeat": a.current_bidder_seat,
        "activeBidders": [str(pid) for pid in a.active_bidders],
        "bidOrder": [str(pid) for pid in a.bid_order],
        "deadline": a.deadline.isoformat() if a.deadline is not None else None,
    }


def _trade_to_dict(trade: object) -> dict:
    """TradeState → dict。"""
    from server.engine.trade import TradeState
    t = trade  # type: TradeState

    def _offer_to_dict(offer: object) -> dict:
        return {
            "properties": offer.properties,
            "cash": offer.cash,
            "jailFreeCard": offer.jail_free_card,
        }

    return {
        "initiatorId": str(t.initiator_id),
        "targetId": str(t.target_id),
        "initiatorOffer": _offer_to_dict(t.initiator_offer),
        "targetOffer": _offer_to_dict(t.target_offer),
        "counterRounds": t.counter_rounds,
        "currentResponder": str(t.current_responder) if t.current_responder is not None else None,
        "deadline": t.deadline.isoformat() if t.deadline is not None else None,
    }


def _game_to_dict(game: GameState) -> dict:
    return {
        "phase": game.phase.value,
        "currentPlayerId": str(game.current_player_id),
        "turnNumber": game.turn_number,
        "turnDeadline": game.turn_deadline.isoformat() if game.turn_deadline else None,
        "tradeWindowAvailable": game.trade_window_available,
        "freeParkingMoney": game.free_parking_money,
        "lastDice": list(game.last_dice) if game.last_dice is not None else None,
        "propertyOwners": {str(k): str(v) for k, v in game.property_owners.items()},
        "mortgageStatus": {str(k): v for k, v in game.mortgage_status.items()},
        "buildingLevels": {str(k): v for k, v in game.building_levels.items()},
        "auction": _auction_to_dict(game.auction) if game.auction is not None else None,
        "trade": _trade_to_dict(game.trade) if game.trade is not None else None,
        "debt": _debt_to_dict(game.debt) if game.debt is not None else None,
        "pendingDecision": _convert_value(game.pending_decision) if game.pending_decision is not None else None,
        "logs": [_convert_value(log) for log in game.logs],
        "winnerPlayerId": str(game.winner_player_id) if game.winner_player_id else None,
    }


def build_public_snapshot(room: RoomState, server_time_ms: int) -> dict:
    """构建纯 JSON 可序列化的公共快照。

    顶层为协议信封 {type, roomVersion, serverTime, state}。
    内部 state 只含房间公共状态，不含信封元数据。
    不包含重连令牌、令牌哈希、WebSocket、锁或运行时对象。
    """
    inner: dict = {
        "code": room.code,
        "phase": room.phase.value,
        "hostPlayerId": str(room.host_player_id),
        "players": [_player_to_dict(p) for p in room.players],
        "createdAt": room.created_at.isoformat() if room.created_at else None,
        "lastNonemptyAt": room.last_nonempty_at.isoformat() if room.last_nonempty_at else None,
    }
    if room.game is not None:
        inner["game"] = _game_to_dict(room.game)
    else:
        inner["game"] = None
    return {
        "type": "state_snapshot",
        "roomVersion": room.version,
        "serverTime": server_time_ms,
        "state": inner,
    }
