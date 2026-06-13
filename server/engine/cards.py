"""卡牌数据驱动定义。

所有卡牌使用稳定 ID 和 action_type 枚举，不存 lambda。
效果参数通过 payload 字段传递，由 execute_card() 统一执行。

对应旧版 monopoly.html 第 1488–1524 行的 CHANCE_CARDS 和 DESTINY_CARDS。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from server.engine.board import BOARD_SIZE, SPACES
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState


# ---------------------------------------------------------------------------
# 卡牌动作类型枚举
# ---------------------------------------------------------------------------


class CardActionType(str, Enum):
    GAIN_MONEY = "gain_money"
    LOSE_MONEY = "lose_money"
    GAIN_JAIL_FREE = "gain_jail_free"
    GO_TO_JAIL = "go_to_jail"
    MOVE_TO_POSITION = "move_to_position"
    MOVE_BACKWARD = "move_backward"
    MOVE_TO_GO = "move_to_go"
    MOVE_TO_FREE_PARKING = "move_to_free_parking"
    BIRTHDAY = "birthday"
    TELEPORT = "teleport"


# ---------------------------------------------------------------------------
# 机会卡定义（12 张，对应旧版 CHANCE_CARDS）
# ---------------------------------------------------------------------------


CHANCE_CARDS: list[dict[str, Any]] = [
    {
        "id": "chance_bank_dividend",
        "text": "银行发放红利！获得 $500",
        "action_type": CardActionType.GAIN_MONEY,
        "payload": {"amount": 500},
    },
    {
        "id": "chance_prize",
        "text": "中奖了！获得 $1000",
        "action_type": CardActionType.GAIN_MONEY,
        "payload": {"amount": 1000},
    },
    {
        "id": "chance_jail_free",
        "text": "出狱免费卡！如果入狱可立即出狱",
        "action_type": CardActionType.GAIN_JAIL_FREE,
        "payload": {},
    },
    {
        "id": "chance_car_repair",
        "text": "汽车维修费 $300",
        "action_type": CardActionType.LOSE_MONEY,
        "payload": {"amount": 300},
    },
    {
        "id": "chance_medical",
        "text": "医疗支出 $500",
        "action_type": CardActionType.LOSE_MONEY,
        "payload": {"amount": 500},
    },
    {
        "id": "chance_move_back_3",
        "text": "后退 3 步",
        "action_type": CardActionType.MOVE_BACKWARD,
        "payload": {"steps": 3},
    },
    {
        "id": "chance_advance_to_go",
        "text": "前进到起点，获得 $1000",
        "action_type": CardActionType.MOVE_TO_GO,
        "payload": {"amount": 1000},
    },
    {
        "id": "chance_birthday",
        "text": "生日快乐！每位玩家给你 $100",
        "action_type": CardActionType.BIRTHDAY,
        "payload": {"amount": 100},
    },
    {
        "id": "chance_house_repair",
        "text": "房屋维修费 $400",
        "action_type": CardActionType.LOSE_MONEY,
        "payload": {"amount": 400},
    },
    {
        "id": "chance_move_to_free_parking",
        "text": "前进到免费停车",
        "action_type": CardActionType.MOVE_TO_FREE_PARKING,
        "payload": {},
    },
    {
        "id": "chance_go_to_jail",
        "text": "前往监狱",
        "action_type": CardActionType.GO_TO_JAIL,
        "payload": {},
    },
    {
        "id": "chance_found_money",
        "text": "捡到钱！获得 $300",
        "action_type": CardActionType.GAIN_MONEY,
        "payload": {"amount": 300},
    },
]


# ---------------------------------------------------------------------------
# 命运卡定义（12 张，对应旧版 DESTINY_CARDS）
# ---------------------------------------------------------------------------


DESTINY_CARDS: list[dict[str, Any]] = [
    {
        "id": "destiny_inheritance",
        "text": "继承遗产！获得 $3000",
        "action_type": CardActionType.GAIN_MONEY,
        "payload": {"amount": 3000},
    },
    {
        "id": "destiny_investment_loss",
        "text": "投资失败，失去 $3000",
        "action_type": CardActionType.LOSE_MONEY,
        "payload": {"amount": 3000},
    },
    {
        "id": "destiny_go_to_jail",
        "text": "前往监狱",
        "action_type": CardActionType.GO_TO_JAIL,
        "payload": {},
    },
    {
        "id": "destiny_teleport",
        "text": "任意传送！",
        "action_type": CardActionType.TELEPORT,
        "payload": {},
    },
    {
        "id": "destiny_bonus",
        "text": "获得 $2000 奖金",
        "action_type": CardActionType.GAIN_MONEY,
        "payload": {"amount": 2000},
    },
    {
        "id": "destiny_fine",
        "text": "缴纳罚款 $1500",
        "action_type": CardActionType.LOSE_MONEY,
        "payload": {"amount": 1500},
    },
    {
        "id": "destiny_advance_to_go",
        "text": "前进到起点，获得 $1000",
        "action_type": CardActionType.MOVE_TO_GO,
        "payload": {"amount": 1000},
    },
    {
        "id": "destiny_jail_free",
        "text": "出狱免费卡！",
        "action_type": CardActionType.GAIN_JAIL_FREE,
        "payload": {},
    },
    {
        "id": "destiny_market_crash",
        "text": "股市崩盘，失去 $2000",
        "action_type": CardActionType.LOSE_MONEY,
        "payload": {"amount": 2000},
    },
    {
        "id": "destiny_jackpot",
        "text": "中大奖！获得 $2500",
        "action_type": CardActionType.GAIN_MONEY,
        "payload": {"amount": 2500},
    },
    {
        "id": "destiny_move_back_2",
        "text": "后退 2 步",
        "action_type": CardActionType.MOVE_BACKWARD,
        "payload": {"steps": 2},
    },
    {
        "id": "destiny_bank_error",
        "text": "银行错误赔付 $1500",
        "action_type": CardActionType.GAIN_MONEY,
        "payload": {"amount": 1500},
    },
]


# ---------------------------------------------------------------------------
# 抽卡函数
# ---------------------------------------------------------------------------


class CardRandomSource(Protocol):
    """卡牌随机源协议。"""

    def roll_die(self) -> int: ...


def draw_card(deck_type: str, random_source: CardRandomSource) -> dict[str, Any]:
    """从指定牌组抽取一张卡。

    deck_type: "chance" 或 "destiny"
    random_source: 随机源，用 roll_die 的结果来选卡
    """
    cards = CHANCE_CARDS if deck_type == "chance" else DESTINY_CARDS
    # 用两次 roll_die 产生一个索引
    idx = (random_source.roll_die() - 1) * 6 + (random_source.roll_die() - 1)
    idx = idx % len(cards)
    return cards[idx]


# ---------------------------------------------------------------------------
# 卡牌执行函数
# ---------------------------------------------------------------------------


def execute_card(
    game: GameState,
    players: list[PlayerState],
    player: PlayerState,
    card: dict[str, Any],
    d1: int,
    d2: int,
) -> EngineResult:
    """执行一张卡牌的效果。

    返回 EngineResult，某些卡牌（如任意传送）会设置 pending_decision
    而不立即执行效果。

    d1, d2: 当前回合的骰子值（用于租金计算等）
    """
    from server.engine.commands import EngineResult

    action_type = card["action_type"]
    payload = card.get("payload", {})
    events: list[dict] = [{"type": "card_drawn", "cardId": card["id"], "text": card["text"]}]

    if action_type == CardActionType.GAIN_MONEY:
        amount = payload["amount"]
        player.money += amount
        events.append({"type": "money_gained", "playerId": str(player.id), "amount": amount})

    elif action_type == CardActionType.LOSE_MONEY:
        amount = payload["amount"]
        player.money -= amount
        # 罚款进免费停车池
        game.free_parking_money += amount
        events.append({"type": "money_lost", "playerId": str(player.id), "amount": amount})

    elif action_type == CardActionType.GAIN_JAIL_FREE:
        player.has_get_out_of_jail_card = True
        events.append({"type": "gained_jail_free_card", "playerId": str(player.id)})

    elif action_type == CardActionType.GO_TO_JAIL:
        player.in_jail = True
        player.position = 10
        player.consecutive_doubles = 0
        events.append({"type": "jailed_by_card", "playerId": str(player.id)})

    elif action_type == CardActionType.MOVE_TO_GO:
        player.position = 0
        amount = payload.get("amount", 1000)
        player.money += amount
        events.append({"type": "moved_to_go", "playerId": str(player.id), "amount": amount})

    elif action_type == CardActionType.MOVE_TO_FREE_PARKING:
        player.position = 20
        events.append({"type": "moved_to_free_parking", "playerId": str(player.id)})

    elif action_type == CardActionType.MOVE_BACKWARD:
        steps = payload["steps"]
        player.position = (player.position - steps + BOARD_SIZE) % BOARD_SIZE
        events.append({"type": "moved_backward", "playerId": str(player.id), "steps": steps, "newPosition": player.position})

    elif action_type == CardActionType.BIRTHDAY:
        amount_per_player = payload["amount"]
        total_gained = 0
        for other in players:
            if other.id != player.id and not other.bankrupt:
                other.money -= amount_per_player
                total_gained += amount_per_player
        player.money += total_gained
        events.append({"type": "birthday_gift", "playerId": str(player.id), "totalGained": total_gained})

    elif action_type == CardActionType.TELEPORT:
        # 任意传送：设置 pending_decision，等待客户端选择目标
        game.pending_decision = {
            "type": "teleport_decision",
            "playerId": str(player.id),
            "cardId": card["id"],
        }
        game.phase = TurnPhase.AWAITING_CARD_DECISION
        events.append({"type": "teleport_pending", "playerId": str(player.id)})
        return EngineResult(changed=True, events=events)

    return EngineResult(changed=True, events=events)
