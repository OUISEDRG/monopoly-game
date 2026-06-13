"""游戏状态模型与回合阶段枚举。

对应设计规范第 10–11 节。复杂子状态（拍卖、交易、债务）
在后续任务中定义，此处以 Any | None 占位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class TurnPhase(str, Enum):
    WAITING_FOR_ROLL = "waiting_for_roll"
    RESOLVING_MOVE = "resolving_move"
    AWAITING_PROPERTY_DECISION = "awaiting_property_decision"
    AWAITING_CARD_DECISION = "awaiting_card_decision"
    AUCTION = "auction"
    TRADE_NEGOTIATION = "trade_negotiation"
    DEBT_RELIEF = "debt_relief"
    TURN_END = "turn_end"
    GAME_OVER = "game_over"


@dataclass(slots=True)
class GameState:
    current_player_id: UUID
    phase: TurnPhase = TurnPhase.WAITING_FOR_ROLL
    turn_number: int = 0
    turn_deadline: datetime | None = None
    trade_window_available: bool = True
    free_parking_money: int = 0
    last_dice: tuple[int, int] | None = None
    property_owners: dict[int, UUID] = field(default_factory=dict)
    mortgage_status: dict[int, bool] = field(default_factory=dict)
    building_levels: dict[int, int] = field(default_factory=dict)
    auction: Any | None = None
    trade: Any | None = None
    debt: Any | None = None
    pending_decision: Any | None = None
    logs: list[dict] = field(default_factory=list)
    winner_player_id: UUID | None = None
