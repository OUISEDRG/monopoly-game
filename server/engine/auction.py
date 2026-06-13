"""多人拍卖引擎。

实现 PLACE_BID / PASS_AUCTION 命令的核心逻辑：
- 按座位循环竞拍
- 最低加价 50
- 出价不得超过当前现金
- 主动退出后不能重新加入该次拍卖
- 无人出价时地产保持无主
- 成交时原子扣款和转移地产
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from server.engine.board import SPACES
from server.engine.commands import EngineResult
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState


# ---------------------------------------------------------------------------
# 拍卖状态
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AuctionState:
    """一次拍卖的完整状态。

    position: 被拍卖的地产位置
    starting_price: 起拍价
    highest_bid: 当前最高出价
    highest_bidder_id: 当前最高出价者 ID
    current_bidder_seat: 当前应出价者的座位号
    active_bidders: 仍在竞拍中的玩家 ID 集合
    bid_order: 按座位排序的竞拍者 ID 列表（仅未破产的）
    """

    position: int
    starting_price: int
    highest_bid: int
    highest_bidder_id: UUID | None
    current_bidder_seat: int
    active_bidders: set[UUID] = field(default_factory=set)
    bid_order: list[UUID] = field(default_factory=list)
    deadline: datetime | None = None


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MIN_BID_INCREMENT: int = 50
DEFAULT_STARTING_PRICE: int = 100


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _find_player_by_id(players: list[PlayerState], player_id: UUID) -> PlayerState | None:
    for p in players:
        if p.id == player_id:
            return p
    return None


def _next_active_bidder(auction: AuctionState) -> UUID | None:
    """从当前座位开始，找到下一个活跃竞拍者。返回 None 表示无活跃竞拍者。"""
    n = len(auction.bid_order)
    if n == 0:
        return None
    start_idx = None
    for i, pid in enumerate(auction.bid_order):
        p = _find_player_by_id.__wrapped__ if hasattr(_find_player_by_id, '__wrapped__') else None
        # 通过座位找索引
        break

    # 找到 current_bidder_seat 在 bid_order 中的索引
    for i, pid in enumerate(auction.bid_order):
        # 需要从 players 中获取座位号，但 bid_order 只有 ID
        # 改用循环方式：从当前位置向后找
        pass

    # 简化：遍历 bid_order 找到座位 >= current_bidder_seat 的活跃竞拍者
    # 然后循环回到前面
    return None


def create_auction(
    game: GameState,
    players: list[PlayerState],
    position: int,
    starting_price: int | None = None,
) -> AuctionState:
    """创建拍卖状态并设置 game.auction 和 game.phase。

    拍卖顺序按座位循环，从触发拍卖的当前玩家的下一个座位开始。
    """
    space = SPACES[position]
    price = starting_price if starting_price is not None else DEFAULT_STARTING_PRICE

    # 按座位排序的未破产玩家
    active_players = sorted(
        [p for p in players if not p.bankrupt],
        key=lambda p: p.seat,
    )
    bid_order = [p.id for p in active_players]
    active_bidders = set(bid_order)

    # 从当前玩家的下一个座位开始
    current_seat = 0
    for i, p in enumerate(active_players):
        if p.id == game.current_player_id:
            current_seat = active_players[(i + 1) % len(active_players)].seat
            break

    auction = AuctionState(
        position=position,
        starting_price=price,
        highest_bid=price,
        highest_bidder_id=None,
        current_bidder_seat=current_seat,
        active_bidders=active_bidders,
        bid_order=bid_order,
    )

    game.auction = auction
    game.phase = TurnPhase.AUCTION
    game.pending_decision = {"type": "auction", "position": position}

    return auction


def _advance_to_next_bidder(auction: AuctionState, players: list[PlayerState]) -> UUID | None:
    """推进到下一个活跃竞拍者，返回其 ID。如果无人则返回 None。

    当只剩一个活跃竞拍者时：
    - 如果该竞拍者是最高出价者，返回 None（成交）
    - 否则返回该竞拍者（让其决定出价或退出）
    """
    # 按座位排序的活跃竞拍者
    active_sorted = sorted(
        [p for p in players if p.id in auction.active_bidders and not p.bankrupt],
        key=lambda p: p.seat,
    )
    if not active_sorted:
        return None

    if len(active_sorted) == 1:
        only_bidder = active_sorted[0]
        if auction.highest_bidder_id == only_bidder.id:
            return None  # 最高出价者就是自己，成交
        # 还没出过价，让其决定
        auction.current_bidder_seat = only_bidder.seat
        return only_bidder.id

    # 找到当前座位之后的下一个活跃竞拍者
    for p in active_sorted:
        if p.seat > auction.current_bidder_seat:
            auction.current_bidder_seat = p.seat
            return p.id

    # 循环回到第一个
    auction.current_bidder_seat = active_sorted[0].seat
    return active_sorted[0].id


# ---------------------------------------------------------------------------
# PLACE_BID 命令
# ---------------------------------------------------------------------------


def apply_place_bid(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    players: list[PlayerState],
) -> EngineResult:
    """处理 PLACE_BID 命令。

    规则：
    - 仅 AUCTION 阶段
    - 仅当前应出价者
    - 出价须 ≥ 当前最高价 + 50
    - 出价不得超过当前现金
    - 更新最高出价和出价者，推进到下一竞拍者
    """
    # 阶段检查
    if game.phase != TurnPhase.AUCTION:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in auction phase"}],
        )

    auction = game.auction
    if auction is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no active auction"}],
        )

    # 是否是活跃竞拍者
    if actor_id not in auction.active_bidders:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_ACTIVE_BIDDER", "message": "you have left the auction"}],
        )

    # 是否是当前应出价者
    player = _find_player_by_id(players, actor_id)
    if player is None:
        return EngineResult(changed=False, events=[])

    if player.seat != auction.current_bidder_seat:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_YOUR_TURN", "message": "not your turn to bid"}],
        )

    # 出价检查
    bid_amount = payload.get("amount")
    if bid_amount is None or not isinstance(bid_amount, int):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "bid amount is required"}],
        )

    min_bid = auction.highest_bid + MIN_BID_INCREMENT
    if bid_amount < min_bid:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "BID_TOO_LOW", "message": f"minimum bid is {min_bid}"}],
        )

    # 超现金检查
    if bid_amount > player.money:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INSUFFICIENT_FUNDS", "message": "bid exceeds your cash"}],
        )

    # 更新拍卖状态
    auction.highest_bid = bid_amount
    auction.highest_bidder_id = actor_id

    # 推进到下一竞拍者
    next_bidder_id = _advance_to_next_bidder(auction, players)

    events: list[dict] = [
        {"type": "bid_placed", "playerId": str(actor_id), "position": auction.position, "amount": bid_amount},
    ]

    if next_bidder_id:
        events.append({"type": "auction_turn", "playerId": str(next_bidder_id), "position": auction.position})
    else:
        # 只剩一人（就是出价者自己），直接成交
        events.extend(_finalize_auction(game, players))

    return EngineResult(changed=True, events=events)


# ---------------------------------------------------------------------------
# PASS_AUCTION 命令
# ---------------------------------------------------------------------------


def apply_pass_auction(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    players: list[PlayerState],
) -> EngineResult:
    """处理 PASS_AUCTION 命令。

    规则：
    - 仅 AUCTION 阶段
    - 仅当前应出价者
    - 退出后不能重新加入
    - 如果只剩一个活跃竞拍者且有最高出价，成交
    - 如果无人出价且无人竞拍，流拍
    """
    # 阶段检查
    if game.phase != TurnPhase.AUCTION:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in auction phase"}],
        )

    auction = game.auction
    if auction is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no active auction"}],
        )

    # 是否是活跃竞拍者
    if actor_id not in auction.active_bidders:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_ACTIVE_BIDDER", "message": "you have left the auction"}],
        )

    # 是否是当前应出价者
    player = _find_player_by_id(players, actor_id)
    if player is None:
        return EngineResult(changed=False, events=[])

    if player.seat != auction.current_bidder_seat:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_YOUR_TURN", "message": "not your turn to pass"}],
        )

    # 退出拍卖
    auction.active_bidders.discard(actor_id)

    events: list[dict] = [
        {"type": "auction_pass", "playerId": str(actor_id), "position": auction.position},
    ]

    remaining = len(auction.active_bidders)

    if remaining == 0:
        # 无人竞拍
        if auction.highest_bidder_id is not None:
            # 有人出过价但最后一人也退了——最高出价者成交
            events.extend(_finalize_auction(game, players))
        else:
            # 无人出价，流拍
            events.extend(_cancel_auction(game, players))
    elif remaining == 1 and auction.highest_bidder_id is not None and auction.highest_bidder_id in auction.active_bidders:
        # 只剩最高出价者自己，成交
        events.extend(_finalize_auction(game, players))
    else:
        # 推进到下一竞拍者（可能只剩一人但无人出价，让其有机会出价）
        next_bidder_id = _advance_to_next_bidder(auction, players)
        if next_bidder_id:
            events.append({"type": "auction_turn", "playerId": str(next_bidder_id), "position": auction.position})
        else:
            # 无下一竞拍者
            if auction.highest_bidder_id is not None:
                events.extend(_finalize_auction(game, players))
            else:
                events.extend(_cancel_auction(game, players))

    return EngineResult(changed=True, events=events)


# ---------------------------------------------------------------------------
# 拍卖结束
# ---------------------------------------------------------------------------


def _finalize_auction(game: GameState, players: list[PlayerState]) -> list[dict]:
    """拍卖成交：扣款 + 转移地产 + 恢复阶段。"""
    auction = game.auction
    assert auction is not None
    assert auction.highest_bidder_id is not None

    winner = _find_player_by_id(players, auction.highest_bidder_id)
    events: list[dict] = []

    if winner is not None:
        winner.money -= auction.highest_bid
        game.property_owners[auction.position] = winner.id
        if auction.position not in winner.properties:
            winner.properties.append(auction.position)
        events.append({
            "type": "auction_won",
            "playerId": str(winner.id),
            "position": auction.position,
            "amount": auction.highest_bid,
        })

    # 清理拍卖状态
    game.auction = None
    game.pending_decision = None

    # 恢复到 WAITING_FOR_ROLL 并推进到下一玩家
    d1, d2 = game.last_dice or (1, 2)
    is_doubles = d1 == d2
    _advance_turn_after_auction(game, players, is_doubles)

    return events


def _cancel_auction(game: GameState, players: list[PlayerState] | None = None) -> list[dict]:
    """拍卖流拍：无人出价，地产保持无主。"""
    auction = game.auction
    assert auction is not None

    events: list[dict] = [
        {"type": "auction_cancelled", "position": auction.position, "reason": "no_bids"},
    ]

    # 清理拍卖状态
    game.auction = None
    game.pending_decision = None

    # 恢复到 WAITING_FOR_ROLL 并推进到下一玩家
    d1, d2 = game.last_dice or (1, 2)
    is_doubles = d1 == d2
    _advance_turn_after_auction(game, players=players, is_doubles=is_doubles)

    return events


def _advance_turn_after_auction(game: GameState, players: list[PlayerState] | None, is_doubles: bool) -> None:
    """拍卖结束后推进回合。"""
    # 拍卖结束后总是推进到下一玩家（不保留双数额外回合）
    game.turn_number += 1
    if players:
        from server.engine.rules import _next_player_id
        game.current_player_id = _next_player_id(players, game.current_player_id)
    game.phase = TurnPhase.WAITING_FOR_ROLL
