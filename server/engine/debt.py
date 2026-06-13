"""债务、破产与游戏结束引擎。

实现 DEBT_ACTION 命令和确定性自动清偿/破产逻辑：
- DebtState: 记录负债玩家、债权人、恢复回调
- DEBT_ACTION: 出售建筑或抵押地产
- 自动处置策略: 先卖房（收益低到高），再抵押（价值低到高）
- 破产清算: 有债权人→资产转移；无债权人→逐块拍卖
- 游戏结束: 仅剩一人→GAME_OVER
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from server.engine.auction import create_auction
from server.engine.board import COLOR_GROUPS, HOUSE_COST, SPACES
from server.engine.commands import EngineResult
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState


# ---------------------------------------------------------------------------
# 债务状态
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DebtState:
    """债务处置状态。

    player_id: 负债玩家 ID
    creditor_id: 债权人 ID（可为 None）
    owed_amount: 负债金额（正数表示欠款）
    deadline: 截止时间（用于超时自动处理）
    completed: 是否已完成处置
    restore_callback: 恢复回调函数
    restore_context: 恢复回调的上下文数据
    """

    player_id: UUID
    creditor_id: UUID | None
    owed_amount: int
    deadline: datetime | None = None
    completed: bool = False
    restore_callback: Callable[[GameState, list[PlayerState]], list[dict]] | None = None
    restore_context: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _find_player(players: list[PlayerState], player_id: UUID) -> PlayerState | None:
    for p in players:
        if p.id == player_id:
            return p
    return None


def _get_owed_amount(player: PlayerState) -> int:
    """计算玩家负债金额。负数现金表示负债。"""
    return max(0, -player.money)


def _has_legal_actions(game: GameState, player: PlayerState) -> bool:
    """检查玩家是否有合法的债务处置操作。"""
    # 检查可出售建筑
    for pos in player.properties:
        if game.building_levels.get(pos, 0) > 0:
            if _can_sell_building(game, player, pos):
                return True

    # 检查可抵押地产
    for pos in player.properties:
        if _can_mortgage(game, player, pos):
            return True

    return False


def _can_sell_building(game: GameState, player: PlayerState, position: int) -> bool:
    """检查是否可以出售该地产的建筑。"""
    if game.building_levels.get(position, 0) <= 0:
        return False
    if game.property_owners.get(position) != player.id:
        return False

    # 同色组平均出售检查
    space = SPACES[position]
    if space.group:
        group_props = COLOR_GROUPS.get(space.group, [])
        current_level = game.building_levels.get(position, 0)
        new_level = current_level - 1
        for p in group_props:
            level = game.building_levels.get(p, 0)
            if p == position:
                level = new_level
            if level - new_level > 1:
                return False

    return True


def _can_mortgage(game: GameState, player: PlayerState, position: int) -> bool:
    """检查是否可以抵押该地产。"""
    if game.property_owners.get(position) != player.id:
        return False
    if game.mortgage_status.get(position, False):
        return False
    if game.building_levels.get(position, 0) > 0:
        return False

    # 同色组内有建筑则不能抵押
    space = SPACES[position]
    if space.group:
        group_props = COLOR_GROUPS.get(space.group, [])
        for p in group_props:
            if game.building_levels.get(p, 0) > 0:
                return False

    return True


def _transfer_property_to_creditor(
    game: GameState,
    players: list[PlayerState],
    position: int,
    debtor: PlayerState,
    creditor: PlayerState,
) -> None:
    """将地产转移给债权人。"""
    game.property_owners[position] = creditor.id
    if position in debtor.properties:
        debtor.properties.remove(position)
    if position not in creditor.properties:
        creditor.properties.append(position)
    # 抵押状态保持不变


def _execute_bankruptcy_with_creditor(
    game: GameState,
    players: list[PlayerState],
    debtor: PlayerState,
    creditor: PlayerState,
) -> list[dict]:
    """有债权人时的破产清算：资产转移给债权人。"""
    events: list[dict] = []

    # 转移所有地产给债权人
    for pos in list(debtor.properties):
        _transfer_property_to_creditor(game, players, pos, debtor, creditor)

    # 转移出狱卡
    if debtor.has_get_out_of_jail_card:
        debtor.has_get_out_of_jail_card = False
        creditor.has_get_out_of_jail_card = True

    # 标记破产
    debtor.bankrupt = True
    debtor.money = 0

    events.append({
        "type": "bankruptcy",
        "playerId": str(debtor.id),
        "creditorId": str(creditor.id),
        "reason": "insufficient_funds",
    })

    return events


def _execute_bankruptcy_without_creditor(
    game: GameState,
    players: list[PlayerState],
    debtor: PlayerState,
) -> list[dict]:
    """无债权人时的破产清算：逐块拍卖地产。"""
    events: list[dict] = []

    # 标记破产
    debtor.bankrupt = True
    debtor.money = 0

    # 释放所有地产（进入拍卖）
    properties_to_auction = list(debtor.properties)
    for pos in properties_to_auction:
        del game.property_owners[pos]
        if pos in debtor.properties:
            debtor.properties.remove(pos)
        game.building_levels[pos] = 0  # 清空建筑

    events.append({
        "type": "bankruptcy",
        "playerId": str(debtor.id),
        "creditorId": None,
        "reason": "insufficient_funds",
    })

    # 开始第一块地产的拍卖
    if properties_to_auction:
        first_pos = properties_to_auction[0]
        create_auction(game, players, first_pos)
        # 记录待拍卖的剩余地产
        game.pending_decision = {
            "type": "bankruptcy_auction",
            "remaining_properties": properties_to_auction[1:],
        }
        events.append({"type": "auction_started", "position": first_pos, "reason": "bankruptcy"})

    return events


def _check_game_over(game: GameState, players: list[PlayerState]) -> bool:
    """检查是否仅剩一个非破产玩家。"""
    active_players = [p for p in players if not p.bankrupt]
    if len(active_players) == 1:
        game.winner_player_id = active_players[0].id
        game.phase = TurnPhase.GAME_OVER
        return True
    return False


# ---------------------------------------------------------------------------
# DEBT_ACTION 命令
# ---------------------------------------------------------------------------


def apply_debt_action(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    players: list[PlayerState],
) -> EngineResult:
    """处理 DEBT_ACTION 命令。

    规则：
    - 仅 DEBT_RELIEF 阶段
    - 仅负债玩家可操作
    - 只允许出售一栋建筑或抵押一处地产
    - 每次操作后重新计算债务
    - 现金恢复到 0 或以上时自动完成债务处置
    - 仍负债且无合法操作时自动破产
    """
    if game.phase != TurnPhase.DEBT_RELIEF:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in debt relief phase"}],
        )

    debt = game.debt
    if debt is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no active debt"}]
        )

    # 只有负债玩家可以操作
    if actor_id != debt.player_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_DEBTOR", "message": "not the debtor"}]
        )

    player = _find_player(players, actor_id)
    if player is None:
        return EngineResult(changed=False, events=[])

    action_type = payload.get("action")
    position = payload.get("position")

    if action_type is None or position is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "action and position required"}]
        )

    events: list[dict] = []

    if action_type == "sell_building":
        # 出售建筑
        if not _can_sell_building(game, player, position):
            return EngineResult(
                changed=False,
                events=[{"type": "command_rejected", "code": "INVALID_ACTION", "message": "cannot sell building"}]
            )

        current_level = game.building_levels[position]
        space = SPACES[position]
        cost = HOUSE_COST.get(space.group, 0) if space.group else 0
        refund = cost // 2

        player.money += refund
        game.building_levels[position] = current_level - 1

        events.append({
            "type": "building_sold",
            "playerId": str(actor_id),
            "position": position,
            "level": current_level - 1,
            "refund": refund,
        })

    elif action_type == "mortgage":
        # 抵押地产
        if not _can_mortgage(game, player, position):
            return EngineResult(
                changed=False,
                events=[{"type": "command_rejected", "code": "INVALID_ACTION", "message": "cannot mortgage property"}]
            )

        space = SPACES[position]
        mortgage_value = (space.price or 0) // 2

        player.money += mortgage_value
        game.mortgage_status[position] = True

        events.append({
            "type": "property_mortgaged",
            "playerId": str(actor_id),
            "position": position,
            "mortgageValue": mortgage_value,
        })

    else:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": f"unknown action: {action_type}"}]
        )

    # 重新评估债务状态
    new_owed = _get_owed_amount(player)

    if player.money >= 0:
        # 债务已还清
        events.append({
            "type": "debt_resolved",
            "playerId": str(actor_id),
            "finalMoney": player.money,
        })
        _finalize_debt_relief(game, players, debt, events)
    elif not _has_legal_actions(game, player):
        # 仍负债且无合法操作，破产
        events.extend(_process_bankruptcy(game, players, player, debt.creditor_id))
        game.debt = None
    else:
        # 更新负债金额，继续债务处置
        debt.owed_amount = new_owed
        events.append({
            "type": "debt_updated",
            "playerId": str(actor_id),
            "owedAmount": new_owed,
        })

    return EngineResult(changed=True, events=events)


# ---------------------------------------------------------------------------
# 自动债务处置（AI）
# ---------------------------------------------------------------------------


def process_auto_debt_relief(
    game: GameState,
    players: list[PlayerState],
    debtor_id: UUID,
    creditor_id: UUID | None = None,
) -> EngineResult:
    """AI 玩家的自动债务处置。

    确定性策略：
    1. 按可出售建筑收益从低到高出售，持续重新扫描平均出售约束
    2. 按抵押价值从低到高抵押
    3. 仍负债则破产
    """
    debtor = _find_player(players, debtor_id)
    if debtor is None:
        return EngineResult(changed=False, events=[])

    events: list[dict] = []
    debt = DebtState(
        player_id=debtor_id,
        creditor_id=creditor_id,
        owed_amount=_get_owed_amount(debtor),
    )
    game.debt = debt
    game.phase = TurnPhase.DEBT_RELIEF

    events.append({
        "type": "debt_relief_started",
        "playerId": str(debtor_id),
        "owedAmount": debt.owed_amount,
    })

    # 阶段 1: 出售建筑（收益从低到高）
    while debtor.money < 0 and _has_legal_actions(game, debtor):
        # 找到可出售的建筑，按收益从低到高排序
        sellable = []
        for pos in debtor.properties:
            if _can_sell_building(game, debtor, pos):
                space = SPACES[pos]
                cost = HOUSE_COST.get(space.group, 0) if space.group else 0
                refund = cost // 2
                sellable.append((refund, pos))

        if sellable:
            sellable.sort(key=lambda x: x[0])  # 收益从低到高
            _, pos = sellable[0]
            current_level = game.building_levels[pos]
            space = SPACES[pos]
            cost = HOUSE_COST.get(space.group, 0) if space.group else 0
            refund = cost // 2

            debtor.money += refund
            game.building_levels[pos] = current_level - 1

            events.append({
                "type": "building_sold",
                "playerId": str(debtor_id),
                "position": pos,
                "level": current_level - 1,
                "refund": refund,
            })
        else:
            break

    # 阶段 2: 抵押地产（价值从低到高）
    while debtor.money < 0 and _has_legal_actions(game, debtor):
        # 找到可抵押的地产，按价值从低到高排序
        mortgageable = []
        for pos in debtor.properties:
            if _can_mortgage(game, debtor, pos):
                space = SPACES[pos]
                value = (space.price or 0) // 2
                mortgageable.append((value, pos))

        if mortgageable:
            mortgageable.sort(key=lambda x: x[0])  # 价值从低到高
            value, pos = mortgageable[0]

            debtor.money += value
            game.mortgage_status[pos] = True

            events.append({
                "type": "property_mortgaged",
                "playerId": str(debtor_id),
                "position": pos,
                "mortgageValue": value,
            })
        else:
            break

    # 阶段 3: 检查结果
    if debtor.money >= 0:
        events.append({
            "type": "debt_resolved",
            "playerId": str(debtor_id),
            "finalMoney": debtor.money,
        })
        _finalize_debt_relief(game, players, debt, events)
    else:
        events.extend(_process_bankruptcy(game, players, debtor, creditor_id))

    game.debt = None
    return EngineResult(changed=True, events=events)


def _finalize_debt_relief(
    game: GameState,
    players: list[PlayerState],
    debt: DebtState,
    events: list[dict],
) -> None:
    """完成债务处置，恢复原流程。"""
    game.debt = None
    game.phase = TurnPhase.WAITING_FOR_ROLL

    # 执行恢复回调（最多一次）
    if debt.restore_callback and not debt.completed:
        debt.completed = True
        additional_events = debt.restore_callback(game, players)
        events.extend(additional_events)


def _process_bankruptcy(
    game: GameState,
    players: list[PlayerState],
    debtor: PlayerState,
    creditor_id: UUID | None,
) -> list[dict]:
    """处理破产。"""
    events: list[dict] = []

    if creditor_id:
        creditor = _find_player(players, creditor_id)
        if creditor and not creditor.bankrupt:
            events.extend(_execute_bankruptcy_with_creditor(game, players, debtor, creditor))
        else:
            events.extend(_execute_bankruptcy_without_creditor(game, players, debtor))
    else:
        events.extend(_execute_bankruptcy_without_creditor(game, players, debtor))

    # 检查游戏是否结束
    _check_game_over(game, players)

    return events
