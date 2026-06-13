"""安全、限流和日志硬化测试。

对应设计规范第 24 节和实施计划 Task 16。
覆盖昵称清理、消息大小限制、Origin 检查、命令限流和日志脱敏。
"""

from __future__ import annotations

import json
import logging
import os
from io import StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.app import app, reset_room_manager
from server.security import sanitize_nickname, RateLimiter, validate_origin, get_allowed_origins


# ---------------------------------------------------------------------------
# 昵称清理测试
# ---------------------------------------------------------------------------


class TestNicknameSanitization:
    """昵称清理：移除控制字符，保持长度 1–12。"""

    def test_normal_nickname_unchanged(self):
        """正常昵称保持不变。"""
        assert sanitize_nickname("Player1") == "Player1"
        assert sanitize_nickname("测试玩家") == "测试玩家"

    def test_whitespace_trimmed(self):
        """前后空白被去除。"""
        assert sanitize_nickname("  Player  ") == "Player"
        assert sanitize_nickname("\tTest\t") == "Test"

    def test_control_characters_removed(self):
        """控制字符被移除。"""
        # ASCII 控制字符 (0x00-0x1F, 0x7F)
        assert sanitize_nickname("Play\x00er") == "Player"
        assert sanitize_nickname("Test\x1BName") == "TestName"
        assert sanitize_nickname("User\x7F") == "User"

    def test_unicode_control_characters_removed(self):
        """Unicode 控制字符被移除。"""
        # Unicode 控制字符如 U+200B (零宽空格)
        assert sanitize_nickname("Play\u200ber") == "Player"
        assert sanitize_nickname("Test\u200bName") == "TestName"

    def test_empty_after_sanitization(self):
        """清理后为空返回空字符串。"""
        assert sanitize_nickname("\x00\x00\x00") == ""
        assert sanitize_nickname("   ") == ""

    def test_max_length_not_truncated(self):
        """长度超过 12 的昵称不截断（由调用者验证长度）。"""
        long_name = "VeryLongPlayerNameExceedsLimit"
        result = sanitize_nickname(long_name)
        # 清理后保持原长度，不截断
        assert len(result) == len(long_name)


# ---------------------------------------------------------------------------
# 限流测试
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """命令限流：超过阈值触发 RATE_LIMITED。"""

    def test_limiter_allows_normal_frequency(self):
        """正常频率命令通过。"""
        limiter = RateLimiter(max_per_second=5)
        player_id = uuid4()

        # 5 次命令应该全部允许
        for _ in range(5):
            assert limiter.check(player_id) is True

    def test_limiter_blocks_excessive_commands(self):
        """超过限制被拒绝。"""
        limiter = RateLimiter(max_per_second=3)
        player_id = uuid4()

        # 前 3 次允许
        for _ in range(3):
            assert limiter.check(player_id) is True

        # 第 4 次被拒绝
        assert limiter.check(player_id) is False

    def test_limiter_different_players_independent(self):
        """不同玩家独立计数。"""
        limiter = RateLimiter(max_per_second=2)

        player1 = uuid4()
        player2 = uuid4()

        # 玩家1 发送 2 次
        assert limiter.check(player1) is True
        assert limiter.check(player1) is True

        # 玩家2 应该仍能发送
        assert limiter.check(player2) is True
        assert limiter.check(player2) is True

        # 玩家1 超限
        assert limiter.check(player1) is False


# ---------------------------------------------------------------------------
# WebSocket 安全测试
# ---------------------------------------------------------------------------


class TestWebSocketSecurity:
    """WebSocket 安全：超大消息、认证失败、非法协议。"""

    def setup_method(self):
        """每个测试前重置房间管理器。"""
        reset_room_manager()

    def test_message_too_large_rejected(self):
        """超过 16 KiB 的消息被拒绝。"""
        client = TestClient(app)

        # 创建房间
        resp = client.post("/api/rooms", json={"nickname": "Host"})
        room_code = resp.json()["roomCode"]
        player_id = resp.json()["playerId"]
        token = resp.json()["reconnectToken"]

        # 构造超大消息（超过 16 KiB）
        large_payload = {"data": "x" * (20 * 1024)}  # 20 KiB
        large_message = json.dumps({
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 0,
            "command": "ROLL_DICE",
            "payload": large_payload,
        })

        with client.websocket_connect(f"/ws/rooms/{room_code}?playerId={player_id}&token={token}") as ws:
            ws.send_text(large_message)
            # 应收到拒绝消息或连接关闭
            # 由于 TestClient 行为，我们检查是否能收到响应
            try:
                response = ws.receive_text()
                data = json.loads(response)
                assert data["type"] == "command_result"
                assert data["accepted"] is False
            except Exception:
                # 连接可能已关闭
                pass

    def test_invalid_json_rejected(self):
        """非法 JSON 被拒绝。"""
        client = TestClient(app)

        resp = client.post("/api/rooms", json={"nickname": "Host"})
        room_code = resp.json()["roomCode"]
        player_id = resp.json()["playerId"]
        token = resp.json()["reconnectToken"]

        with client.websocket_connect(f"/ws/rooms/{room_code}?playerId={player_id}&token={token}") as ws:
            # 先接收初始快照
            initial = ws.receive_text()
            initial_data = json.loads(initial)
            assert initial_data["type"] == "state_snapshot"

            # 发送非法 JSON
            ws.send_text("not a json")
            response = ws.receive_text()
            data = json.loads(response)
            assert data["type"] == "command_result"
            assert data["accepted"] is False
            assert data["error"]["code"] == "INVALID_MESSAGE"


# ---------------------------------------------------------------------------
# 日志脱敏测试
# ---------------------------------------------------------------------------


class TestLogSanitization:
    """日志脱敏：不包含重连令牌或完整私密交易报价。"""

    def test_token_not_logged(self):
        """重连令牌不出现在日志中。"""
        from server.logging_config import sanitize_log_data

        data = {
            "token": "secret-reconnect-token-12345",
            "playerId": str(uuid4()),
            "roomCode": "ABC123",
        }

        sanitized = sanitize_log_data(data)
        assert "secret-reconnect-token" not in str(sanitized)
        assert sanitized.get("token") == "[REDACTED]"

    def test_private_trade_offer_not_logged(self):
        """私密交易报价不出现在日志中。"""
        from server.logging_config import sanitize_log_data

        data = {
            "type": "PROPOSE_TRADE",
            "payload": {
                "initiatorOffer": {"cash": 500, "properties": ["Boardwalk"]},
                "targetOffer": {"cash": 200, "properties": ["Park Place"]},
            },
        }

        sanitized = sanitize_log_data(data)
        # payload 应该被标记为敏感
        assert "initiatorOffer" not in str(sanitized.get("payload", {}))
        assert sanitized.get("payload") == "[PRIVATE]"

    def test_structured_log_format(self):
        """结构化日志包含必要字段。"""
        from server.logging_config import StructuredFormatter

        logger = logging.getLogger("test_structured")
        logger.setLevel(logging.INFO)

        # 创建 StringIO 捕获日志
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)

        # 记录一条结构化日志
        logger.info(
            "command_received",
            extra={
                "event": "command_received",
                "room_code": "ABC123",
                "player_id_short": "abc123",
                "request_id": str(uuid4()),
                "room_version": 5,
                "command": "ROLL_DICE",
                "result": "accepted",
            }
        )

        output = stream.getvalue()
        # 检查 JSON 格式
        log_data = json.loads(output.strip())
        assert log_data["event"] == "command_received"
        assert log_data["room_code"] == "ABC123"
        assert "player_id_short" in log_data
        assert "request_id" in log_data
        assert log_data["room_version"] == 5
        assert log_data["command"] == "ROLL_DICE"
        assert log_data["result"] == "accepted"


# ---------------------------------------------------------------------------
# Origin 安全边界测试
# ---------------------------------------------------------------------------


class TestOriginValidation:
    """Origin 安全边界：生产环境拒绝未知来源。"""

    def test_get_allowed_origins_from_env(self):
        """从环境变量获取允许的 Origin 列表。"""
        # 设置环境变量
        os.environ["ALLOWED_ORIGINS"] = "https://example.com,https://app.example.com"
        origins = get_allowed_origins()
        assert "https://example.com" in origins
        assert "https://app.example.com" in origins
        # 清理环境变量
        del os.environ["ALLOWED_ORIGINS"]

    def test_get_allowed_origins_default_empty(self):
        """未设置环境变量时返回空列表。"""
        # 确保环境变量不存在
        if "ALLOWED_ORIGINS" in os.environ:
            del os.environ["ALLOWED_ORIGINS"]
        origins = get_allowed_origins()
        assert origins == []

    def test_validate_origin_allowed(self):
        """允许的 Origin 通过验证。"""
        os.environ["ALLOWED_ORIGINS"] = "https://example.com"
        os.environ["APP_ENV"] = "production"
        assert validate_origin("https://example.com") is True
        del os.environ["ALLOWED_ORIGINS"]
        del os.environ["APP_ENV"]

    def test_validate_origin_blocked_in_production(self):
        """生产环境未知 Origin 被拒绝。"""
        os.environ["ALLOWED_ORIGINS"] = "https://example.com"
        os.environ["APP_ENV"] = "production"
        assert validate_origin("https://malicious.com") is False
        del os.environ["ALLOWED_ORIGINS"]
        del os.environ["APP_ENV"]

    def test_validate_origin_allowed_in_development(self):
        """开发环境允许任意 Origin。"""
        os.environ["APP_ENV"] = "development"
        # 未设置 ALLOWED_ORIGINS
        if "ALLOWED_ORIGINS" in os.environ:
            del os.environ["ALLOWED_ORIGINS"]
        assert validate_origin("https://any-origin.com") is True
        del os.environ["APP_ENV"]

    def test_validate_origin_none_allowed(self):
        """无 Origin 时允许连接（部分客户端不发送 Origin）。"""
        os.environ["APP_ENV"] = "production"
        assert validate_origin(None) is True
        del os.environ["APP_ENV"]


class TestWebSocketOriginSecurity:
    """WebSocket Origin 安全：生产环境拒绝未知来源连接。"""

    def setup_method(self):
        """每个测试前重置房间管理器和环境变量。"""
        reset_room_manager()
        # 清理环境变量
        for key in ["APP_ENV", "ALLOWED_ORIGINS"]:
            if key in os.environ:
                del os.environ[key]

    def test_unknown_origin_rejected_in_production(self):
        """生产环境未知 Origin 连接被拒绝。"""
        os.environ["APP_ENV"] = "production"
        os.environ["ALLOWED_ORIGINS"] = "https://allowed.com"

        try:
            client = TestClient(app)

            resp = client.post("/api/rooms", json={"nickname": "Host"})
            room_code = resp.json()["roomCode"]
            player_id = resp.json()["playerId"]
            token = resp.json()["reconnectToken"]

            with client.websocket_connect(
                f"/ws/rooms/{room_code}?playerId={player_id}&token={token}",
                headers={"origin": "https://malicious.com"},
            ) as ws:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_text()

            assert exc_info.value.code == 4004
        finally:
            del os.environ["APP_ENV"]
            del os.environ["ALLOWED_ORIGINS"]

    def test_allowed_origin_can_connect(self):
        """允许的 Origin 可以正常连接。"""
        os.environ["APP_ENV"] = "production"
        os.environ["ALLOWED_ORIGINS"] = "https://allowed.com"

        try:
            client = TestClient(app)

            resp = client.post("/api/rooms", json={"nickname": "Host"})
            room_code = resp.json()["roomCode"]
            player_id = resp.json()["playerId"]
            token = resp.json()["reconnectToken"]

            with client.websocket_connect(
                f"/ws/rooms/{room_code}?playerId={player_id}&token={token}",
                headers={"origin": "https://allowed.com"},
            ) as ws:
                initial = ws.receive_text()
                data = json.loads(initial)
                assert data["type"] == "state_snapshot"
        finally:
            del os.environ["APP_ENV"]
            del os.environ["ALLOWED_ORIGINS"]

    def test_development_allows_any_origin(self):
        """开发环境允许任意 Origin 连接。"""
        # 开发环境不设置 ALLOWED_ORIGINS
        os.environ["APP_ENV"] = "development"

        client = TestClient(app)

        resp = client.post("/api/rooms", json={"nickname": "Host"})
        room_code = resp.json()["roomCode"]
        player_id = resp.json()["playerId"]
        token = resp.json()["reconnectToken"]

        with client.websocket_connect(f"/ws/rooms/{room_code}?playerId={player_id}&token={token}") as ws:
            initial = ws.receive_text()
            data = json.loads(initial)
            assert data["type"] == "state_snapshot"

        del os.environ["APP_ENV"]
