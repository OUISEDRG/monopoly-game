"""玩家状态模型。

对应设计规范第 9 节。重连令牌哈希存于服务器私密身份记录，
不进入 PlayerState 或公共快照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class PlayerState:
    id: UUID
    nickname: str
    seat: int
    color: str
    ready: bool = False
    connected: bool = True
    disconnected_at: datetime | None = None
    bankrupt: bool = False
    money: int = 15000
    position: int = 0
    properties: list[int] = field(default_factory=list)
    in_jail: bool = False
    jail_turns: int = 0
    has_get_out_of_jail_card: bool = False
    consecutive_doubles: int = 0
