"""权威回合规则引擎。

实现 ROLL_DICE、BUY_PROPERTY、DECLINE_PROPERTY 命令的核心逻辑：
- 随机源产生骰子值，客户端不可指定
- 经过起点加 2000
- 双数获得额外回合
- 连续三次双数进监狱
- 非双数普通落点后推进到下一玩家
- 非当前玩家/错误阶段拒绝执行
- 落点分发：无主地产→购买决策，有主→租金，税费→免费停车池，卡牌→抽卡
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Protocol
from uuid import UUID

from server.engine.auction import apply_pass_auction, apply_place_bid
from server.engine.board import BOARD_SIZE, COLOR_GROUPS, HOUSE_COST, RENT_MULTIPLIER, SPACES
from server.engine.cards import draw_card, execute_card
from server.engine.commands import EngineResult
from server.engine.debt import apply_debt_action
from server.engine.trade import apply_accept_trade, apply_counter_trade, apply_propose_trade, apply_reject_trade
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState
from server.protocol import CommandName


# ---------------------------------------------------------------------------
# 随机源协议和实现
# ---------------------------------------------------------------------------


class RandomSource(Protocol):
    """可注入的骰子随机源协议。"""

    def roll_die(self) -> int: ...


class SystemRandomSource:
    """生产环境使用的系统随机源。"""

    def __init__(self) -> None:
        self._random = random.SystemRandom()

    def roll_die(self) -> int:
        return self._random.randint(1, 6)


class FixedRandomSource:
    """测试用固定随机源，按顺序返回预定义骰子值。

    rolls: 骰子值列表，每两个为一组 (d1, d2)。
    超出列表后循环回到开头。
    """

    def __init__(self, rolls: list[int]) -> None:
        self._rolls = rolls
        self._index = 0

    def roll_die(self) -> int:
        value = self._rolls[self._index % len(self._rolls)]
        self._index += 1
        return value


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _find_player(players: list[PlayerState], player_id: UUID) -> PlayerState | None:
    for p in players:
        if p.id == player_id:
            return p
    return None


def _next_player_id(players: list[PlayerState], current_id: UUID) -> UUID:
    """返回下一个未破产玩家的 ID。"""
    active = [p for p in players if not p.bankrupt]
    if len(active) <= 1:
        return current_id
    for i, p in enumerate(active):
        if p.id == current_id:
            return active[(i + 1) % len(active)].id
    return current_id


def _calculate_rent(
    game: GameState,
    position: int,
    owner: PlayerState,
    d1: int,
    d2: int,
) -> int:
    """计算指定位置的租金。

    规则：
    - 抵押地产不收租
    - 无垄断空地：base_rent
    - 垄断且无建筑：base_rent × 2
    - 有建筑：base_rent × RENT_MULTIPLIER[level]
    """
    space = SPACES[position]
    if not space.base_rent:
        return 0

    # 抵押地产不收租
    if game.mortgage_status.get(position, False):
        return 0

    group = space.group
    if not group:
        return space.base_rent

    group_props = COLOR_GROUPS.get(group, [])
    owned_in_group = sum(1 for p in group_props if game.property_owners.get(p) == owner.id)
    houses = game.building_levels.get(position, 0)
    has_monopoly = owned_in_group == len(group_props)

    # 垄断且无建筑：基础租金翻倍
    if has_monopoly and houses == 0:
        return space.base_rent * 2

    # 有建筑：基础租金 × 倍率
    if houses > 0:
        level = min(houses, len(RENT_MULTIPLIER) - 1)
        return space.base_rent * RENT_MULTIPLIER[level]

    # 无垄断空地
    return space.base_rent


def _advance_turn(game: GameState, players: list[PlayerState], actor_id: UUID, is_doubles: bool) -> None:
    """推进回合：双数额外回合，非双数推进到下一玩家。"""
    if is_doubles:
        game.phase = TurnPhase.WAITING_FOR_ROLL
    else:
        player = _find_player(players, actor_id)
        if player:
            player.consecutive_doubles = 0
        game.turn_number += 1
        game.current_player_id = _next_player_id(players, actor_id)
        game.phase = TurnPhase.WAITING_FOR_ROLL


# ---------------------------------------------------------------------------
# 落点分发
# ---------------------------------------------------------------------------


def _dispatch_landing(
    game: GameState,
    players: list[PlayerState],
    player: PlayerState,
    position: int,
    d1: int,
    d2: int,
    is_doubles: bool,
    random_source: RandomSource,
) -> list[dict]:
    """根据落点空间类型分发处理逻辑。

    返回事件列表。某些落点会改变 game.phase（如无主地产进入购买决策）。
    """
    space = SPACES[position]
    events: list[dict] = [{"type": "landed", "playerId": str(player.id), "position": position, "spaceType": space.type}]

    if space.type == "go":
        # 起点已在移动时处理加钱，此处无额外决策
        _advance_turn(game, players, player.id, is_doubles)

    elif space.type == "property":
        owner_id = game.property_owners.get(position)
        if owner_id is None:
            # 无主地产
            if player.money >= (space.price or 0):
                game.phase = TurnPhase.AWAITING_PROPERTY_DECISION
                game.pending_decision = {
                    "type": "property_decision",
                    "position": position,
                    "playerId": str(player.id),
                }
                events.append({"type": "property_decision_pending", "playerId": str(player.id), "position": position, "price": space.price})
            else:
                # 资金不足，进入拍卖
                game.phase = TurnPhase.AUCTION
                game.pending_decision = {
                    "type": "auction",
                    "position": position,
                }
                events.append({"type": "auction_started", "position": position, "reason": "insufficient_funds"})
        elif owner_id != player.id:
            # 有主地产：支付租金
            owner = _find_player(players, owner_id)
            if owner is not None:
                rent = _calculate_rent(game, position, owner, d1, d2)
                if rent > 0:
                    player.money -= rent
                    owner.money += rent
                    events.append({"type": "rent_paid", "fromPlayerId": str(player.id), "toPlayerId": str(owner_id), "amount": rent, "position": position})
                else:
                    events.append({"type": "rent_skipped", "reason": "mortgaged", "position": position})
            _advance_turn(game, players, player.id, is_doubles)
        else:
            # 自己的地产，无操作
            _advance_turn(game, players, player.id, is_doubles)

    elif space.type == "tax":
        if space.name == "所得税":
            tax_amount = max(200, min(2000, int(player.money * 0.1)))
            player.money -= tax_amount
            game.free_parking_money += tax_amount
            events.append({"type": "tax_paid", "playerId": str(player.id), "amount": tax_amount, "taxType": "income"})
        else:
            # 豪宅税：拥有8+建筑时，每个建筑缴纳100
            total_buildings = sum(game.building_levels.get(pos, 0) for pos in player.properties)
            if total_buildings >= 8:
                luxury_tax = total_buildings * 100
                player.money -= luxury_tax
                game.free_parking_money += luxury_tax
                events.append({"type": "tax_paid", "playerId": str(player.id), "amount": luxury_tax, "taxType": "luxury", "buildings": total_buildings})
            else:
                events.append({"type": "tax_skipped", "reason": "below_threshold", "buildings": total_buildings})
        _advance_turn(game, players, player.id, is_doubles)

    elif space.type == "freeParking":
        # 免费停车无决策
        _advance_turn(game, players, player.id, is_doubles)

    elif space.type == "goToJail":
        player.in_jail = True
        player.position = 10
        player.consecutive_doubles = 0
        events.append({"type": "jailed_by_landing", "playerId": str(player.id)})
        # 进监狱后推进到下一玩家
        game.turn_number += 1
        game.current_player_id = _next_player_id(players, player.id)
        game.phase = TurnPhase.WAITING_FOR_ROLL

    elif space.type == "jail":
        # 只是路过监狱（探视），无操作
        _advance_turn(game, players, player.id, is_doubles)

    elif space.type == "chance":
        card = draw_card("chance", random_source)
        card_result = execute_card(game, players, player, card, d1, d2)
        events.extend(card_result.events)
        # 如果卡牌没有设置 pending_decision（如任意传送），则正常推进
        if game.phase != TurnPhase.AWAITING_CARD_DECISION:
            # 卡牌可能导致位置变化（如前往监狱），需要检查
            if player.in_jail:
                # 已在 execute_card 中处理进监狱
                game.turn_number += 1
                game.current_player_id = _next_player_id(players, player.id)
                game.phase = TurnPhase.WAITING_FOR_ROLL
            else:
                _advance_turn(game, players, player.id, is_doubles)

    elif space.type == "destiny":
        card = draw_card("destiny", random_source)
        card_result = execute_card(game, players, player, card, d1, d2)
        events.extend(card_result.events)
        if game.phase != TurnPhase.AWAITING_CARD_DECISION:
            if player.in_jail:
                game.turn_number += 1
                game.current_player_id = _next_player_id(players, player.id)
                game.phase = TurnPhase.WAITING_FOR_ROLL
            else:
                _advance_turn(game, players, player.id, is_doubles)

    else:
        # 未知空间类型，正常推进
        _advance_turn(game, players, player.id, is_doubles)

    return events


# ---------------------------------------------------------------------------
# 核心命令处理
# ---------------------------------------------------------------------------


def apply_command(
    game: GameState,
    actor_id: UUID,
    command: CommandName,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """应用一条命令到游戏状态，返回 EngineResult。"""
    if command == CommandName.ROLL_DICE:
        return _apply_roll_dice(game, actor_id, payload, random_source, now, players)
    elif command == CommandName.BUY_PROPERTY:
        return _apply_buy_property(game, actor_id, payload, random_source, now, players)
    elif command == CommandName.DECLINE_PROPERTY:
        return _apply_decline_property(game, actor_id, payload, random_source, now, players)
    elif command == CommandName.BUILD:
        return _apply_build(game, actor_id, payload, random_source, now, players)
    elif command == CommandName.SELL_BUILDING:
        return _apply_sell_building(game, actor_id, payload, random_source, now, players)
    elif command == CommandName.MORTGAGE:
        return _apply_mortgage(game, actor_id, payload, random_source, now, players)
    elif command == CommandName.UNMORTGAGE:
        return _apply_unmortgage(game, actor_id, payload, random_source, now, players)
    elif command == CommandName.PLACE_BID:
        return apply_place_bid(game, actor_id, payload, players)
    elif command == CommandName.PASS_AUCTION:
        return apply_pass_auction(game, actor_id, payload, players)
    elif command == CommandName.PROPOSE_TRADE:
        return apply_propose_trade(game, actor_id, payload, players)
    elif command == CommandName.ACCEPT_TRADE:
        return apply_accept_trade(game, actor_id, payload, players)
    elif command == CommandName.REJECT_TRADE:
        return apply_reject_trade(game, actor_id, payload, players)
    elif command == CommandName.COUNTER_TRADE:
        return apply_counter_trade(game, actor_id, payload, players)
    elif command == CommandName.DEBT_ACTION:
        return apply_debt_action(game, actor_id, payload, players)

    # 未知命令（后续任务实现）
    return EngineResult(
        changed=False,
        events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": f"unknown command: {command}"}],
    )


def _apply_roll_dice(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """处理 ROLL_DICE 命令。"""

    # 阶段检查
    if game.phase != TurnPhase.WAITING_FOR_ROLL:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in roll phase"}],
        )

    # 当前玩家检查
    if actor_id != game.current_player_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_CURRENT_PLAYER", "message": "not your turn"}],
        )

    player = _find_player(players, actor_id)
    if player is None:
        return EngineResult(changed=False, events=[])

    # 掷骰（忽略 payload 中的任何骰子值）
    d1 = random_source.roll_die()
    d2 = random_source.roll_die()
    total = d1 + d2
    is_doubles = d1 == d2

    # 记录骰子
    game.last_dice = (d1, d2)

    events: list[dict] = [{"type": "dice_rolled", "d1": d1, "d2": d2, "total": total}]

    # 三次双数进监狱
    if is_doubles and player.consecutive_doubles >= 2:
        player.in_jail = True
        player.position = 10  # 监狱位置
        player.consecutive_doubles = 0
        game.turn_number += 1
        game.current_player_id = _next_player_id(players, actor_id)
        game.phase = TurnPhase.WAITING_FOR_ROLL
        events.append({"type": "jailed_for_doubles", "playerId": str(actor_id)})
        return EngineResult(changed=True, events=events)

    # 移动
    old_position = player.position
    new_position = (old_position + total) % BOARD_SIZE
    player.position = new_position

    # 经过起点加钱
    if old_position + total >= BOARD_SIZE:
        player.money += 2000
        events.append({"type": "passed_go", "playerId": str(actor_id), "amount": 2000})

    # 落点分发
    landing_events = _dispatch_landing(game, players, player, new_position, d1, d2, is_doubles, random_source)
    events.extend(landing_events)

    # 双数处理（仅在落点没有改变阶段时）
    if is_doubles and game.phase == TurnPhase.WAITING_FOR_ROLL:
        player.consecutive_doubles += 1
        events.append({"type": "doubles_extra_turn", "playerId": str(actor_id)})

    return EngineResult(changed=True, events=events)


def _apply_buy_property(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """处理 BUY_PROPERTY 命令。"""

    # 阶段检查
    if game.phase != TurnPhase.AWAITING_PROPERTY_DECISION:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in property decision phase"}],
        )

    # 当前玩家检查
    if actor_id != game.current_player_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_CURRENT_PLAYER", "message": "not your turn"}],
        )

    player = _find_player(players, actor_id)
    if player is None:
        return EngineResult(changed=False, events=[])

    # 检查 pending_decision
    if game.pending_decision is None or game.pending_decision.get("type") != "property_decision":
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no pending property decision"}],
        )

    position = game.pending_decision["position"]
    space = SPACES[position]

    # 资金检查
    if player.money < (space.price or 0):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INSUFFICIENT_FUNDS", "message": "not enough money"}],
        )

    # 执行购买
    player.money -= space.price
    game.property_owners[position] = player.id
    player.properties.append(position)
    game.pending_decision = None

    events: list[dict] = [
        {"type": "property_bought", "playerId": str(actor_id), "position": position, "price": space.price},
    ]

    # 购买后推进回合
    # 需要知道是否是双数（从 last_dice 获取）
    d1, d2 = game.last_dice or (1, 2)
    is_doubles = d1 == d2
    _advance_turn(game, players, actor_id, is_doubles)

    return EngineResult(changed=True, events=events)


def _apply_decline_property(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """处理 DECLINE_PROPERTY 命令。放弃购买进入拍卖。"""

    # 阶段检查
    if game.phase != TurnPhase.AWAITING_PROPERTY_DECISION:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in property decision phase"}],
        )

    # 当前玩家检查
    if actor_id != game.current_player_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_CURRENT_PLAYER", "message": "not your turn"}],
        )

    # 检查 pending_decision
    if game.pending_decision is None or game.pending_decision.get("type") != "property_decision":
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "no pending property decision"}],
        )

    position = game.pending_decision["position"]
    game.pending_decision = {"type": "auction", "position": position}
    game.phase = TurnPhase.AUCTION

    events: list[dict] = [
        {"type": "property_declined", "playerId": str(actor_id), "position": position},
        {"type": "auction_started", "position": position, "reason": "declined"},
    ]

    return EngineResult(changed=True, events=events)


# ---------------------------------------------------------------------------
# 建造 / 出售建筑 / 抵押 / 解押
# ---------------------------------------------------------------------------


def _validate_waiting_for_roll(game: GameState, actor_id: UUID, players: list[PlayerState]) -> EngineResult | PlayerState:
    """WAITING_FOR_ROLL 阶段 + 当前玩家校验，返回 player 或 EngineResult。"""
    if game.phase != TurnPhase.WAITING_FOR_ROLL:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_PHASE", "message": "not in waiting_for_roll phase"}],
        )
    if actor_id != game.current_player_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_CURRENT_PLAYER", "message": "not your turn"}],
        )
    player = _find_player(players, actor_id)
    if player is None:
        return EngineResult(changed=False, events=[])
    return player


def _check_complete_color_group(game: GameState, position: int, owner_id: UUID) -> str | None:
    """检查 position 所在色组是否完整拥有。返回色组名或 None。"""
    space = SPACES[position]
    if not space.group:
        return None
    group_props = COLOR_GROUPS.get(space.group, [])
    if all(game.property_owners.get(p) == owner_id for p in group_props):
        return space.group
    return None


def _check_no_mortgage_in_group(game: GameState, group: str) -> bool:
    """检查色组内是否有抵押地产。无抵押返回 True。"""
    group_props = COLOR_GROUPS.get(group, [])
    return all(not game.mortgage_status.get(p, False) for p in group_props)


def _check_even_building(game: GameState, position: int, group: str) -> bool:
    """检查在 position 建造后是否满足平均建设（同色组差 ≤ 1）。"""
    group_props = COLOR_GROUPS.get(group, [])
    current_level = game.building_levels.get(position, 0)
    new_level = current_level + 1
    for p in group_props:
        if p == position:
            level = new_level
        else:
            level = game.building_levels.get(p, 0)
        if new_level - level > 1:
            return False
    return True


def _apply_build(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """处理 BUILD 命令。

    规则：
    - 仅 WAITING_FOR_ROLL + 当前玩家
    - 须完整色组
    - 色组内无抵押
    - 平均建设（同色组差 ≤ 1）
    - 最大等级 4（地标）
    - 资金须足够支付建房费
    """
    player_or_err = _validate_waiting_for_roll(game, actor_id, players)
    if isinstance(player_or_err, EngineResult):
        return player_or_err
    player = player_or_err

    position = payload.get("position")
    if position is None or not isinstance(position, int):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "position is required"}],
        )

    # 所有权检查
    if game.property_owners.get(position) != actor_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "not your property"}],
        )

    space = SPACES[position]
    if not space.group:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "cannot build on this space"}],
        )

    # 完整色组检查
    group = _check_complete_color_group(game, position, actor_id)
    if group is None:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INCOMPLETE_COLOR_GROUP", "message": "must own all properties in color group"}],
        )

    # 抵押检查
    if not _check_no_mortgage_in_group(game, group):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "MORTGAGED_PROPERTY", "message": "cannot build on mortgaged color group"}],
        )

    # 等级上限
    current_level = game.building_levels.get(position, 0)
    if current_level >= 4:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "MAX_LEVEL_REACHED", "message": "property already at max level"}],
        )

    # 平均建设检查
    if not _check_even_building(game, position, group):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "UNEVEN_BUILDING", "message": "must build evenly within color group"}],
        )

    # 资金检查
    cost = HOUSE_COST.get(group, 0)
    if player.money < cost:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INSUFFICIENT_FUNDS", "message": "not enough money to build"}],
        )

    # 执行建造
    player.money -= cost
    game.building_levels[position] = current_level + 1

    events: list[dict] = [
        {"type": "building_built", "playerId": str(actor_id), "position": position, "level": current_level + 1, "cost": cost},
    ]
    return EngineResult(changed=True, events=events)


def _check_even_selling(game: GameState, position: int, group: str) -> bool:
    """检查在 position 出售后是否满足平均出售（同色组差 ≤ 1）。"""
    group_props = COLOR_GROUPS.get(group, [])
    current_level = game.building_levels.get(position, 0)
    new_level = current_level - 1
    for p in group_props:
        if p == position:
            level = new_level
        else:
            level = game.building_levels.get(p, 0)
        if level - new_level > 1:
            return False
    return True


def _apply_sell_building(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """处理 SELL_BUILDING 命令。

    规则：
    - 仅 WAITING_FOR_ROLL + 当前玩家
    - 退款 50%（建房费的一半）
    - 平均出售
    """
    player_or_err = _validate_waiting_for_roll(game, actor_id, players)
    if isinstance(player_or_err, EngineResult):
        return player_or_err
    player = player_or_err

    position = payload.get("position")
    if position is None or not isinstance(position, int):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "position is required"}],
        )

    # 所有权检查
    if game.property_owners.get(position) != actor_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "not your property"}],
        )

    # 等级检查
    current_level = game.building_levels.get(position, 0)
    if current_level <= 0:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NO_BUILDING", "message": "no building to sell"}],
        )

    space = SPACES[position]
    group = space.group

    # 平均出售检查
    if group and not _check_even_selling(game, position, group):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "UNEVEN_SELLING", "message": "must sell evenly within color group"}],
        )

    # 执行出售：退款 50%
    cost = HOUSE_COST.get(group, 0) if group else 0
    refund = cost // 2
    player.money += refund
    game.building_levels[position] = current_level - 1

    events: list[dict] = [
        {"type": "building_sold", "playerId": str(actor_id), "position": position, "level": current_level - 1, "refund": refund},
    ]
    return EngineResult(changed=True, events=events)


def _apply_mortgage(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """处理 MORTGAGE 命令。

    规则：
    - 仅 WAITING_FOR_ROLL + 当前玩家
    - 获得抵押价值（地产价格的一半）
    - 阻止收租和建造
    - 有建筑的地产须先出售所有建筑
    """
    player_or_err = _validate_waiting_for_roll(game, actor_id, players)
    if isinstance(player_or_err, EngineResult):
        return player_or_err
    player = player_or_err

    position = payload.get("position")
    if position is None or not isinstance(position, int):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "position is required"}],
        )

    # 所有权检查
    if game.property_owners.get(position) != actor_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "not your property"}],
        )

    # 已抵押检查
    if game.mortgage_status.get(position, False):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "ALREADY_MORTGAGED", "message": "property already mortgaged"}],
        )

    # 有建筑不能抵押
    if game.building_levels.get(position, 0) > 0:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "HAS_BUILDINGS", "message": "must sell all buildings before mortgaging"}],
        )

    # 执行抵押
    space = SPACES[position]
    mortgage_value = (space.price or 0) // 2
    player.money += mortgage_value
    game.mortgage_status[position] = True

    events: list[dict] = [
        {"type": "property_mortgaged", "playerId": str(actor_id), "position": position, "mortgageValue": mortgage_value},
    ]
    return EngineResult(changed=True, events=events)


def _apply_unmortgage(
    game: GameState,
    actor_id: UUID,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
    players: list[PlayerState],
) -> EngineResult:
    """处理 UNMORTGAGE 命令。

    规则：
    - 仅 WAITING_FOR_ROLL + 当前玩家
    - 付抵押价值 × 1.1 解押
    - 资金须足够
    """
    player_or_err = _validate_waiting_for_roll(game, actor_id, players)
    if isinstance(player_or_err, EngineResult):
        return player_or_err
    player = player_or_err

    position = payload.get("position")
    if position is None or not isinstance(position, int):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "position is required"}],
        )

    # 所有权检查
    if game.property_owners.get(position) != actor_id:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INVALID_COMMAND", "message": "not your property"}],
        )

    # 未抵押检查
    if not game.mortgage_status.get(position, False):
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "NOT_MORTGAGED", "message": "property is not mortgaged"}],
        )

    # 解押费用 = 抵押价值 × 1.1
    space = SPACES[position]
    mortgage_value = (space.price or 0) // 2
    unmortgage_cost = int(mortgage_value * 1.1)

    # 资金检查
    if player.money < unmortgage_cost:
        return EngineResult(
            changed=False,
            events=[{"type": "command_rejected", "code": "INSUFFICIENT_FUNDS", "message": "not enough money to unmortgage"}],
        )

    # 执行解押
    player.money -= unmortgage_cost
    game.mortgage_status[position] = False

    events: list[dict] = [
        {"type": "property_unmortgaged", "playerId": str(actor_id), "position": position, "cost": unmortgage_cost},
    ]
    return EngineResult(changed=True, events=events)
