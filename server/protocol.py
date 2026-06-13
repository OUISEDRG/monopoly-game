"""客户端命令协议、错误码枚举和命令结果信封。

对应设计规范第 11、14、15、23、24 节。
只负责协议解析校验和结果构造，不实现业务逻辑。
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictInt, ValidationError


# ---------------------------------------------------------------------------
# 命令名称枚举
# ---------------------------------------------------------------------------


class CommandName(str, Enum):
    SET_READY = "SET_READY"
    START_GAME = "START_GAME"
    LEAVE_ROOM = "LEAVE_ROOM"
    ROLL_DICE = "ROLL_DICE"
    PROPOSE_TRADE = "PROPOSE_TRADE"
    BUILD = "BUILD"
    SELL_BUILDING = "SELL_BUILDING"
    MORTGAGE = "MORTGAGE"
    UNMORTGAGE = "UNMORTGAGE"
    BUY_PROPERTY = "BUY_PROPERTY"
    DECLINE_PROPERTY = "DECLINE_PROPERTY"
    PLACE_BID = "PLACE_BID"
    PASS_AUCTION = "PASS_AUCTION"
    ACCEPT_TRADE = "ACCEPT_TRADE"
    REJECT_TRADE = "REJECT_TRADE"
    COUNTER_TRADE = "COUNTER_TRADE"
    DEBT_ACTION = "DEBT_ACTION"


# ---------------------------------------------------------------------------
# 错误码枚举
# ---------------------------------------------------------------------------


class ErrorCode(str, Enum):
    INVALID_MESSAGE = "INVALID_MESSAGE"
    INVALID_NICKNAME = "INVALID_NICKNAME"
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
    ROOM_FULL = "ROOM_FULL"
    ROOM_ALREADY_STARTED = "ROOM_ALREADY_STARTED"
    NICKNAME_TAKEN = "NICKNAME_TAKEN"
    AUTH_FAILED = "AUTH_FAILED"
    NOT_HOST = "NOT_HOST"
    NOT_READY = "NOT_READY"
    NOT_CURRENT_PLAYER = "NOT_CURRENT_PLAYER"
    INVALID_PHASE = "INVALID_PHASE"
    INVALID_COMMAND = "INVALID_COMMAND"
    STALE_STATE = "STALE_STATE"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    ASSET_CHANGED = "ASSET_CHANGED"
    RATE_LIMITED = "RATE_LIMITED"


# ---------------------------------------------------------------------------
# 消息大小限制
# ---------------------------------------------------------------------------

_MAX_MESSAGE_BYTES = 16 * 1024  # 16 KiB


# ---------------------------------------------------------------------------
# Pydantic 命令模型
# ---------------------------------------------------------------------------


class ClientCommand(BaseModel):
    """客户端命令信封。

    外部字段使用 camelCase（requestId, roomVersion），
    解析后属性为 snake_case（request_id, room_version）。
    禁止未知顶层字段。
    """

    model_config = {"extra": "forbid"}

    type: Literal["command"]
    request_id: UUID = Field(alias="requestId")
    room_version: int = Field(default=..., ge=0, strict=True, alias="roomVersion")
    command: CommandName
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 解析入口
# ---------------------------------------------------------------------------


def parse_client_command(raw_text: str) -> ClientCommand:
    """解析客户端 WebSocket 文本消息为 ClientCommand。

    - 超过 16 KiB 拒绝
    - 非 JSON / 非对象 / 字段缺失 / 类型错误 → INVALID_MESSAGE
    - 未知命令 → INVALID_COMMAND
    - 不泄露内部堆栈
    """
    # 大小检查
    if len(raw_text.encode("utf-8")) > _MAX_MESSAGE_BYTES:
        raise ValueError("INVALID_MESSAGE: message exceeds 16 KiB")

    # JSON 解析
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("INVALID_MESSAGE: invalid JSON")

    # 顶层必须是对象
    if not isinstance(data, dict):
        raise ValueError("INVALID_MESSAGE: top level must be a JSON object")

    # 在 Pydantic 校验前检查 command 是否为已知命令
    # 缺失 command 归类为 INVALID_MESSAGE
    # 非字符串 command 归类为 INVALID_MESSAGE
    # 存在但未知字符串 command 归类为 INVALID_COMMAND
    raw_command = data.get("command")
    if raw_command is None:
        # 缺失 command，让 Pydantic 报错
        pass
    elif not isinstance(raw_command, str):
        raise ValueError("INVALID_MESSAGE: command must be a string")
    else:
        valid_values = {e.value for e in CommandName}
        if raw_command not in valid_values:
            raise ValueError("INVALID_COMMAND: unknown command name")

    # Pydantic 校验
    try:
        return ClientCommand.model_validate(data)
    except ValidationError:
        raise ValueError("INVALID_MESSAGE: validation failed")


# ---------------------------------------------------------------------------
# 结果构造器
# ---------------------------------------------------------------------------


def accepted_result(request_id: UUID, room_version: int) -> dict:
    """构造命令接受响应。不改变房间版本，不实现幂等缓存或业务。"""
    return {
        "type": "command_result",
        "requestId": str(request_id),
        "accepted": True,
        "roomVersion": room_version,
    }


def rejected_result(
    request_id: UUID,
    room_version: int,
    code: ErrorCode,
    message: str,
) -> dict:
    """构造命令拒绝响应。UUID 和枚举转为 JSON 字符串值。"""
    return {
        "type": "command_result",
        "requestId": str(request_id),
        "accepted": False,
        "roomVersion": room_version,
        "error": {
            "code": code.value,
            "message": message,
        },
    }
