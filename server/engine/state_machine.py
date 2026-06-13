"""回合状态机。

将 apply_command 与房间管理器集成，处理命令分发、
状态转换和事件广播。后续任务（Task 13）将在此处
添加版本控制和幂等检查。
"""

from __future__ import annotations

from server.engine.commands import EngineResult
from server.engine.rules import apply_command

# 重新导出，方便外部引用
__all__ = ["EngineResult", "apply_command"]
