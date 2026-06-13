"""结构化日志配置和脱敏工具。

对应设计规范第 24 节和实施计划 Task 16。
提供 JSON 格式日志输出和敏感数据脱敏。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any


# ---------------------------------------------------------------------------
# 环境配置
# ---------------------------------------------------------------------------


def get_log_level() -> str:
    """从环境变量获取日志级别。"""
    return os.getenv("LOG_LEVEL", "INFO").upper()


def get_app_env() -> str:
    """从环境变量获取应用环境。"""
    return os.getenv("APP_ENV", "development").lower()


# ---------------------------------------------------------------------------
# 敏感数据脱敏
# ---------------------------------------------------------------------------


_SENSITIVE_KEYS = {
    "token",
    "reconnectToken",
    "reconnect_token",
    "password",
    "secret",
    "apiKey",
    "api_key",
}

_PRIVATE_PAYLOAD_COMMANDS = {
    "PROPOSE_TRADE",
    "COUNTER_TRADE",
}


def sanitize_log_data(data: dict[str, Any]) -> dict[str, Any]:
    """脱敏日志数据，移除敏感字段。

    - 令牌类字段替换为 [REDACTED]
    - 私密交易报价替换为 [PRIVATE]
    - 其他字段保持不变
    """
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        # 令牌类字段脱敏
        if key.lower() in _SENSITIVE_KEYS or key in _SENSITIVE_KEYS:
            result[key] = "[REDACTED]"
            continue

        # 私密交易 payload 脱敏
        if key == "payload" and isinstance(value, dict):
            command = data.get("command") or data.get("type")
            if command in _PRIVATE_PAYLOAD_COMMANDS:
                result[key] = "[PRIVATE]"
                continue

        # 递归处理嵌套字典
        if isinstance(value, dict):
            result[key] = sanitize_log_data(value)
        else:
            result[key] = value

    return result


def sanitize_player_id(player_id: str) -> str:
    """将完整 UUID 缩短为前 8 位用于日志。"""
    if not player_id:
        return "unknown"
    # 取前 8 位作为短标识
    return player_id[:8] if len(player_id) >= 8 else player_id


def sanitize_room_code(room_code: str) -> str:
    """房间码保持原样，但确保格式正确。"""
    if not room_code:
        return "unknown"
    return room_code.upper()


# ---------------------------------------------------------------------------
# 结构化日志格式化器
# ---------------------------------------------------------------------------


class StructuredFormatter(logging.Formatter):
    """JSON 结构化日志格式化器。

    输出格式包含：
    - timestamp: ISO 8601 时间戳
    - level: 日志级别
    - event: 事件名称（从消息或 extra 获取）
    - room_code: 脱敏房间标识
    - player_id_short: 玩家短标识
    - request_id: 请求 ID
    - room_version: 房间版本
    - command: 命令名称
    - result: 命令结果
    - error_code: 错误码
    """

    def format(self, record: logging.LogRecord) -> str:
        """将日志记录格式化为 JSON。"""
        # 基础字段
        log_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
        }

        # 消息作为事件名
        if record.msg:
            log_data["event"] = record.msg

        # 从 extra 提取结构化字段
        extra_fields = [
            "event",
            "room_code",
            "player_id_short",
            "request_id",
            "room_version",
            "command",
            "result",
            "error_code",
            "message",
        ]

        for field in extra_fields:
            if hasattr(record, field):
                value = getattr(record, field)
                if value is not None:
                    log_data[field] = value

        # 脱敏处理
        if "room_code" in log_data:
            log_data["room_code"] = sanitize_room_code(log_data["room_code"])
        if "player_id_short" in log_data:
            log_data["player_id_short"] = sanitize_player_id(log_data["player_id_short"])

        # 如果有 args，尝试格式化消息
        if record.args:
            try:
                formatted_msg = record.msg % record.args
                log_data["message"] = formatted_msg
            except Exception:
                pass

        return json.dumps(log_data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 日志配置函数
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    """配置应用日志。

    - 开发环境：使用简单格式
    - 生产环境：使用 JSON 结构化格式
    """
    log_level = get_log_level()
    app_env = get_app_env()

    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 添加新处理器
    handler = logging.StreamHandler()

    if app_env == "production":
        # 生产环境使用 JSON 格式
        handler.setFormatter(StructuredFormatter())
    else:
        # 开发环境使用简单格式
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))

    root_logger.addHandler(handler)


# ---------------------------------------------------------------------------
# 安全日志辅助函数
# ---------------------------------------------------------------------------


def log_command_event(
    logger: logging.Logger,
    event: str,
    room_code: str,
    player_id: str,
    request_id: str,
    room_version: int,
    command: str,
    result: str,
    error_code: str | None = None,
) -> None:
    """记录命令事件的结构化日志。"""
    logger.info(
        event,
        extra={
            "event": event,
            "room_code": sanitize_room_code(room_code),
            "player_id_short": sanitize_player_id(player_id),
            "request_id": request_id,
            "room_version": room_version,
            "command": command,
            "result": result,
            "error_code": error_code,
        }
    )


def log_security_event(
    logger: logging.Logger,
    event: str,
    room_code: str | None = None,
    player_id: str | None = None,
    reason: str | None = None,
) -> None:
    """记录安全事件的结构化日志。"""
    extra = {
        "event": event,
        "category": "security",
    }
    if room_code:
        extra["room_code"] = sanitize_room_code(room_code)
    if player_id:
        extra["player_id_short"] = sanitize_player_id(player_id)
    if reason:
        extra["reason"] = reason

    logger.warning(event, extra=extra)