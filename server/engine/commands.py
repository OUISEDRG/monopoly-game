"""引擎命令结果数据类。

EngineResult 是 apply_command 的返回值，携带状态是否改变、
公共事件列表和按玩家 ID 分发的私密事件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(slots=True)
class EngineResult:
    """apply_command 的返回值。

    changed: 是否产生了有效状态变更（调用方据此决定是否递增版本）
    events: 公共事件列表，广播给所有客户端
    private_events: 按玩家 ID 分发的私密事件（如手牌信息）
    """

    changed: bool
    events: list[dict] = field(default_factory=list)
    private_events: dict[UUID, list[dict]] = field(default_factory=dict)
