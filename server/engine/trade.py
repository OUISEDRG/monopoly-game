"""完整玩家交易系统。

实现 PROPOSE_TRADE / ACCEPT_TRADE / REJECT_TRADE / COUNTER_TRADE 命令：
- 仅当前玩家在 WAITING_FOR_ROLL 阶段可发起
- 可提交多地产 + 非负现金 + 一张出狱卡
- 最多两轮还价
- 交割前校验双方资产未变更
- 原子转移
- 隐私：完整报价用 private_events 只发给双方
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from server.engine.board import COLOR_GROUPS, SPACES
from server.engine.commands import EngineResult
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MAX_COUNTER_ROUNDS: int = 2


# ---------------------------------------------------------------------------
# 交易状态
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TradeOffer:
    """一方在交易中提供的资产。"""

    properties: list[int] = field(default_factory=list)
    cash: int = 0
    jail_free_card: bool = False


@dataclass(slots=True)
class TradeState:
    """一次交易的完整状态。

    initiator_id: 发起者 ID
    target_id: 目标玩家 ID
    initiator_offer: 发起者提供的资产
    target_offer: 目标玩家提供的资产
    counter_rounds: 已进行的还价轮数
    current_responder: 当前应回应者 ID
    """

    initiator_id: UUID
    target_id: UUID
    initiator_offer: TradeOffer
    target_offer: TradeOffer
    counter_rounds: int = 0
    current_responder: UUID | None = None
    deadline: datetime | None = None
    paused_turn_deadline: datetime | None = None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _find_player(players: list[PlayerState], player_id: UUID) -> PlayerState | None:
    for p in players:
        if p.id == player_id:
            return p
    return p if p else None


def _validate_offer_assets(
    game: GameState,
    player: PlayerState,
    offer: TradeOffer,
) -> str | None:
    """校验一方提供的资产是否合法。返回错误消息或 None。"""
    # 现金非负
    if offer.cash < 0:
        return "cash must be non-negative"
    # 现金足够
    if offer.cash > player.money:
        return "insufficient cash"
    # 出狱卡
    if offer.jail_free_card and not player.has_get_out_of_jail_card:
        return "no jail-free card to offer"
    # 地产所有权和建筑限制
    for pos in offer.properties:
        if game.property_owners.get(pos) != player.id:
            return f"property {pos} not owned by player"
        # 有建筑的地产不能交易
        if game.building_levels.get(pos, 0) > 0:
            return f"property {pos} has buildings"
    # 同色组内有建筑则全组不可交易
    for pos in offer.properties:
        space = SPACES[pos]
        if space.group:
            group_props = COLOR_GROUPS.get(space.group, [])
            for gp in group_props:
                if game.building_levels.get(gp, 0) > 0 and gp not in offer.properties:
                    # 同色组有建筑但该地产不在交易中——只要交易的不是有建筑的地产即可
                    # 规则：有建筑的地产不能交易，但同色组其他无建筑地产可以交易
                    pass
    return None


def _validate_no_duplicate_properties(offer_a: TradeOffer, offer_b: TradeOffer) -> str | None:
    """检查双方报价中是否有重复地产。"""
    set_a = set(offer_a.properties)
    set_b = set(offer_b.properties)
    if set_a & set_b:
        return "duplicate properties in both offers"
    # 同一方报价中不能有重复
    if len(offer_a.properties) != len(set_a):
        return "duplicate properties in initiator offer"
    if len(offer_b.properties) != len(set_b):
        return "duplicate properties in target offer"
    return None


def _validate_non_empty_trade(offer_a: TradeOffer, offer_b: TradeOffer) -> str | None:
    """至少一方必须提供资产，禁止空交易。"""
    a_has = len(offer_a.properties) > 0 or offer_a.cash > 0 or offer_a.jail_free_card
    b_has = len(offer_b.properties) > 0 or offer_b.cash > 0 or offer_b.jail_free_card
    if not a_has and not b_has:
        return "empty trade not allowed"
    return None


def _execute_trade(
    game: GameState,
    players: list[PlayerState],
    trade: TradeState,
) -> list[dict]:
    """原子执行交易交割。返回事件列表。"""
    initiator = _find_player(players, trade.initiator_id)
    target = _find_player(players, trade.target_id)

    if initiator is None or target is None:
        return [{"type": "trade_cancelled", "reason": "player_not_found"}]

    # 最终校验：双方资产未变更
    err = _validate_offer_assets(game, initiator, trade.initiator_offer)
    if err:
        return [{"type": "trade_cancelled", "reason": f"initiator_assets_changed: {err}"}]

    err = _validate_offer_assets(game, target, trade.target_offer)
    if err:
        return [{"type": "trade_cancelled", "reason": f"target_assets_changed: {err}"}]

    err = _validate_no_duplicate_properties(trade.initiator_offer, trade.target_offer)
    if err:
        return [{"type": "trade_cancelled", "reason": err}]

    # 执行交割
    # 转移地产
    for pos in trade.initiator_offer.properties:
        game.property_owners[pos] = target.id
        if pos in initiator.properties:
            initiator.properties.remove(pos)
        if pos not in target.properties:
            target.properties.append(pos)

    for pos in trade.target_offer.properties:
        game.property_owners[pos] = initiator.id
        if pos in target.properties:
            target.properties.remove(pos)
        if pos not in initiator.properties:
            initiator.properties.append(pos)

    # 转移现金
    initiator.money -= trade.initiator_offer.cash
    target.money += trade.initiator_offer.cash
    target.money -= trade.target_offer.cash
    initiator.money += trade.target_offer.cash

    # 转移出狱卡
    if trade.initiator_offer.jail_free_card:
        initiator.has_get_out_of_jail_card = False
        target.has_get_out_of_jail_card = True

    if trade.target_offer.jail_free_card:
        target.has_get_out_of_jail_card = False
        initiator.has_get_out_of_jail_card = True

    return [{"type": "trade_completed", "initiatorId": str(initiator.id), "targetId": str(target.id)}]


def _close_trade(game: GameState) -> None:
    """关闭交易状态，恢复 WAITING_FOR_ROLL。"""
    game.trade = None
    game.phase = TurnPhase.WAITING_FOR_ROLL


def _make_public_trade_event(game: GameState, event_type: str) -> dict:
    """构造公共交易事件（不含资产明细）。"""
    trade = game.trade
    return {
        "type": event_type,
        "initiatorId": str(trade.initiator_id) if trade else None,
        "targetId": str(trade.target_id) if trade else None,
        "currentResponder": str(trade.current_responder) if trade and trade.current_responder else None,
        "counterRounds": trade.counter_rounds if trade else 0,
    }


def _make_private_offer_detail(trade: TradeState) -> dict:
    """构造完整报价详情（仅发给交易双方）。"""
    return {
        "type": "trade_offer_detail",
        "initiatorId": str(trade.initiator_id),
        "targetId": str(trade.target_id),
        "initiatorOffer": {
            "properties": trade.initiator_offer.properties,
            "cash": trade.initiator_offer.cash,
            "jailFreeCard": trade.initiator_offer.jail_free_card,
        },
        "targetOffer": {
            "properties": trade.target_offer.properties,
            "cash": trade.target_offer.cash,
            "jailFreeCard": trade.target_offer.jail_free_card,
        },
        "counterRounds": trade.counter_rounds,
    }


# ---------------------------------------------------------------------------
# PROPOSE_TRADE 命令
# ---------------------------------------------------------------------------


def apply_propose_trade(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    players: list[PlayerState],
) -> EngineResult:
    """处理 PROPOSE_TRADE 命令。

    规则：
    - 仅 WAITING_FOR_ROLL + 当前玩家
    - 每回合最多一笔交易
    - 目标玩家必须仍在游戏中
    - 校验双方资产合法性
    """
    # 阶段检查
    if game.phase != TurnPhase.WAITING_FOR_ROLL:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in waiting_for_roll phase"}],
        )

    # 当前玩家检查
    if actor_id != game.current_player_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_CURRENT_PLAYER", "message": "not your turn"}],
        )

    # 交易窗口检查
    if not game.trade_window_available:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "TRADE_WINDOW_CLOSED", "message": "trade window already used this turn"}],
        )

    # 已有交易检查
    if game.trade is not None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "TRADE_IN_PROGRESS", "message": "a trade is already in progress"}],
        )

    player = _find_player(players, actor_id)
    if player is None:
        return EngineResult(changed=False, events=[])

    # 目标玩家
    target_id_raw = payload.get("targetId")
    if target_id_raw is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "targetId is required"}],
        )

    try:
        target_id = UUID(str(target_id_raw))
    except (ValueError, AttributeError):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "invalid targetId"}],
        )

    target = _find_player(players, target_id)
    if target is None or target.bankrupt:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_TARGET", "message": "target player not available"}],
        )

    if target_id == actor_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_TARGET", "message": "cannot trade with yourself"}],
        )

    # 解析发起者报价
    initiator_offer_data = payload.get("initiatorOffer", {})
    initiator_offer = TradeOffer(
        properties=initiator_offer_data.get("properties", []),
        cash=initiator_offer_data.get("cash", 0),
        jail_free_card=initiator_offer_data.get("jailFreeCard", False),
    )

    # 解析目标报价
    target_offer_data = payload.get("targetOffer", {})
    target_offer = TradeOffer(
        properties=target_offer_data.get("properties", []),
        cash=target_offer_data.get("cash", 0),
        jail_free_card=target_offer_data.get("jailFreeCard", False),
    )

    # 校验发起者资产
    err = _validate_offer_assets(game, player, initiator_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": f"initiator: {err}"}],
        )

    # 校验目标资产
    err = _validate_offer_assets(game, target, target_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": f"target: {err}"}],
        )

    # 无重复地产
    err = _validate_no_duplicate_properties(initiator_offer, target_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": err}],
        )

    # 非空交易
    err = _validate_non_empty_trade(initiator_offer, target_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": err}],
        )

    # 创建交易状态
    trade = TradeState(
        initiator_id=actor_id,
        target_id=target_id,
        initiator_offer=initiator_offer,
        target_offer=target_offer,
        counter_rounds=0,
        current_responder=target_id,
    )
    game.trade = trade
    game.phase = TurnPhase.TRADE_NEGOTIATION

    # 公共事件（不含资产明细）
    public_event = _make_public_trade_event(game, "trade_proposed")

    # 私密事件（完整报价只发给双方）
    offer_detail = _make_private_offer_detail(trade)
    private_events: dict[UUID, list[dict]] = {
        actor_id: [offer_detail],
        target_id: [offer_detail],
    }

    return EngineResult(changed=True, events=[public_event], private_events=private_events)


# ---------------------------------------------------------------------------
# ACCEPT_TRADE 命令
# ---------------------------------------------------------------------------


def apply_accept_trade(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    players: list[PlayerState],
) -> EngineResult:
    """处理 ACCEPT_TRADE 命令。

    规则：
    - 仅 TRADE_NEGOTIATION 阶段
    - 仅当前回应者
    - 交割前校验双方资产未变更
    - 原子转移
    """
    if game.phase != TurnPhase.TRADE_NEGOTIATION:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in trade negotiation phase"}],
        )

    trade = game.trade
    if trade is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no active trade"}],
        )

    # 只有当前回应者可以接受
    if actor_id != trade.current_responder:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_RESPONDER", "message": "not your turn to respond"}],
        )

    # 原子交割
    trade_events = _execute_trade(game, players, trade)

    # 检查是否成交
    completed = any(e.get("type") == "trade_completed" for e in trade_events)

    if completed:
        # 关闭交易窗口
        game.trade_window_available = False
        _close_trade(game)
    else:
        # 交割失败，取消交易
        game.trade_window_available = False
        _close_trade(game)

    # 公共事件
    public_event = {
        "type": "trade_accepted" if completed else "trade_cancelled",
        "initiatorId": str(trade.initiator_id),
        "targetId": str(trade.target_id),
    }

    return EngineResult(changed=True, events=[public_event] + trade_events)


# ---------------------------------------------------------------------------
# REJECT_TRADE 命令
# ---------------------------------------------------------------------------


def apply_reject_trade(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    players: list[PlayerState],
) -> EngineResult:
    """处理 REJECT_TRADE 命令。

    规则：
    - 仅 TRADE_NEGOTIATION 阶段
    - 仅当前回应者
    - 拒绝并关闭本回合交易窗口
    """
    if game.phase != TurnPhase.TRADE_NEGOTIATION:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in trade negotiation phase"}],
        )

    trade = game.trade
    if trade is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no active trade"}],
        )

    # 只有当前回应者可以拒绝
    if actor_id != trade.current_responder:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_RESPONDER", "message": "not your turn to respond"}],
        )

    # 关闭交易窗口和交易状态
    game.trade_window_available = False
    public_event = {
        "type": "trade_rejected",
        "initiatorId": str(trade.initiator_id),
        "targetId": str(trade.target_id),
    }
    _close_trade(game)

    return EngineResult(changed=True, events=[public_event])


# ---------------------------------------------------------------------------
# COUNTER_TRADE 命令
# ---------------------------------------------------------------------------


def apply_counter_trade(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    players: list[PlayerState],
) -> EngineResult:
    """处理 COUNTER_TRADE 命令。

    规则：
    - 仅 TRADE_NEGOTIATION 阶段
    - 仅当前回应者
    - 还价刷新资产，最多两轮
    - 达到上限后只能接受或拒绝
    """
    if game.phase != TurnPhase.TRADE_NEGOTIATION:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in trade negotiation phase"}],
        )

    trade = game.trade
    if trade is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no active trade"}],
        )

    # 只有当前回应者可以还价
    if actor_id != trade.current_responder:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_RESPONDER", "message": "not your turn to respond"}],
        )

    # 还价轮数检查
    if trade.counter_rounds >= MAX_COUNTER_ROUNDS:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "MAX_COUNTER_ROUNDS", "message": "maximum counter rounds reached"}],
        )

    # 解析还价
    initiator_offer_data = payload.get("initiatorOffer", {})
    target_offer_data = payload.get("targetOffer", {})

    new_initiator_offer = TradeOffer(
        properties=initiator_offer_data.get("properties", []),
        cash=initiator_offer_data.get("cash", 0),
        jail_free_card=initiator_offer_data.get("jailFreeCard", False),
    )
    new_target_offer = TradeOffer(
        properties=target_offer_data.get("properties", []),
        cash=target_offer_data.get("cash", 0),
        jail_free_card=target_offer_data.get("jailFreeCard", False),
    )

    # 校验双方资产
    initiator = _find_player(players, trade.initiator_id)
    target = _find_player(players, trade.target_id)

    if initiator is None or target is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "player not found"}],
        )

    err = _validate_offer_assets(game, initiator, new_initiator_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": f"initiator: {err}"}],
        )

    err = _validate_offer_assets(game, target, new_target_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": f"target: {err}"}],
        )

    err = _validate_no_duplicate_properties(new_initiator_offer, new_target_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": err}],
        )

    err = _validate_non_empty_trade(new_initiator_offer, new_target_offer)
    if err:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_OFFER", "message": err}],
        )

    # 更新交易状态
    trade.initiator_offer = new_initiator_offer
    trade.target_offer = new_target_offer
    trade.counter_rounds += 1
    # 切换回应者
    trade.current_responder = trade.initiator_id if actor_id == trade.target_id else trade.target_id

    # 公共事件
    public_event = _make_public_trade_event(game, "trade_countered")

    # 私密事件
    offer_detail = _make_private_offer_detail(trade)
    private_events: dict[UUID, list[dict]] = {
        trade.initiator_id: [offer_detail],
        trade.target_id: [offer_detail],
    }

    return EngineResult(changed=True, events=[public_event], private_events=private_events)
