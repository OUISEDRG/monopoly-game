"""重连令牌签发与校验工具。

对应设计规范第 23、24 节。明文令牌只发给客户端一次，
服务器只存储 SHA-256 摘要，使用 secrets.compare_digest 防时序攻击。
包含 Origin 安全边界校验。
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID


# ---------------------------------------------------------------------------
# 昵称清理
# ---------------------------------------------------------------------------


# 控制字符正则：ASCII 控制字符 (0x00-0x1F, 0x7F) 和 Unicode 控制字符
_CONTROL_CHAR_PATTERN = re.compile(
    r"[\x00-\x1F\x7F\u200B-\u200D\uFEFF\u00AD]"
)

_MAX_NICKNAME_LENGTH = 12


def sanitize_nickname(nickname: str) -> str:
    """清理昵称，移除控制字符。

    - 移除 ASCII 和 Unicode 控制字符
    - 去除前后空白
    - 不截断长度（长度检查由调用者处理）
    - 返回清理后的字符串（可能为空或超过长度限制）
    """
    if not nickname:
        return ""

    # 移除控制字符
    cleaned = _CONTROL_CHAR_PATTERN.sub("", nickname)

    # 去除前后空白
    cleaned = cleaned.strip()

    return cleaned


# ---------------------------------------------------------------------------
# Origin 安全边界
# ---------------------------------------------------------------------------


def get_allowed_origins() -> list[str]:
    """从环境变量获取允许的 Origin 列表。

    ALLOWED_ORIGINS 格式：逗号分隔的 URL 列表
    例如：https://example.com,https://app.example.com

    返回：允许的 Origin 列表（未设置时返回空列表）
    """
    origins_str = os.getenv("ALLOWED_ORIGINS", "")
    if not origins_str:
        return []

    # 分割并清理
    origins = [o.strip() for o in origins_str.split(",") if o.strip()]
    return origins


def get_app_env() -> str:
    """从环境变量获取应用环境。

    返回：production 或 development（默认 development）
    """
    return os.getenv("APP_ENV", "development").lower()


def validate_origin(origin: str | None) -> bool:
    """校验 WebSocket 连接的 Origin。

    - 生产环境：只允许 ALLOWED_ORIGINS 中的 Origin
    - 开发环境：允许任意 Origin
    - 无 Origin 时允许连接（部分客户端不发送）

    返回：True 表示允许，False 表示拒绝
    """
    # 无 Origin 时允许（部分客户端不发送）
    if origin is None:
        return True

    # 开发环境允许任意 Origin
    app_env = get_app_env()
    if app_env != "production":
        return True

    # 生产环境检查 ALLOWED_ORIGINS
    allowed = get_allowed_origins()
    if not allowed:
        # 生产环境未配置 ALLOWED_ORIGINS 时，允许任意 Origin
        # 这是为了避免配置错误导致服务完全不可用
        return True

    # 检查 Origin 是否在允许列表中
    return origin in allowed


# ---------------------------------------------------------------------------
# 限流器
# ---------------------------------------------------------------------------


@dataclass
class RateLimiter:
    """基于滑动窗口的命令限流器。

    每个玩家独立计数，超过阈值后拒绝命令。
    """

    max_per_second: int = 10
    window_seconds: float = 1.0

    # 玩家 ID -> (时间戳列表)
    _requests: dict[Hashable, list[float]] = field(default_factory=dict)

    def check(self, player_id: Hashable) -> bool:
        """检查玩家是否被允许发送命令。

        返回 True 表示允许，False 表示被限流。
        """
        now = time.time()
        window_start = now - self.window_seconds

        # 获取玩家的请求记录
        requests = self._requests.get(player_id, [])

        # 清理过期请求
        requests = [t for t in requests if t >= window_start]

        # 检查是否超过限制
        if len(requests) >= self.max_per_second:
            # 更新记录（不添加新请求）
            self._requests[player_id] = requests
            return False

        # 添加当前请求
        requests.append(now)
        self._requests[player_id] = requests
        return True

    def reset(self, player_id: Hashable) -> None:
        """重置玩家的限流计数。"""
        self._requests.pop(player_id, None)

    def clear_all(self) -> None:
        """清空所有限流记录。"""
        self._requests.clear()


# ---------------------------------------------------------------------------
# 重连令牌
# ---------------------------------------------------------------------------


def issue_reconnect_token() -> tuple[str, str]:
    """签发重连令牌，返回 (明文令牌, SHA-256 十六进制摘要)。

    明文令牌只在此处生成，不存入任何状态模型。
    """
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, digest


def verify_reconnect_token(token: str, expected_digest: str) -> bool:
    """校验重连令牌是否匹配存储的摘要。

    使用 secrets.compare_digest 防止时序攻击。
    """
    if not token or not expected_digest:
        return False
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return secrets.compare_digest(actual, expected_digest)
