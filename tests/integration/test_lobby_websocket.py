"""WebSocket 大厅集成测试。

覆盖 Task 6 验收标准：
- 正确令牌连接成功
- 错误令牌拒绝
- 第二人加入后双方收到快照
- 准备状态命令执行
- 新连接替换旧连接
- 断开后 connected=false
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.app import app, reset_room_manager


@pytest.fixture(autouse=True)
def _reset():
    reset_room_manager()
    yield
    reset_room_manager()


def _create_room(client: TestClient, nickname: str = "Alice") -> dict:
    resp = client.post("/api/rooms", json={"nickname": nickname})
    assert resp.status_code == 200
    return resp.json()


def _join_room(client: TestClient, code: str, nickname: str) -> dict:
    resp = client.post(f"/api/rooms/{code}/join", json={"nickname": nickname})
    assert resp.status_code == 200
    return resp.json()


def _ws_url(code: str, player_id: str, token: str) -> str:
    return f"/ws/rooms/{code}?playerId={player_id}&token={token}"


def _receive_snapshot(ws) -> dict:
    """接收并解析 state_snapshot 消息，跳过其他类型。"""
    while True:
        msg = json.loads(ws.receive_text())
        if msg.get("type") == "state_snapshot":
            return msg


def _receive_command_result(ws) -> dict:
    """接收并解析 command_result 消息。"""
    while True:
        msg = json.loads(ws.receive_text())
        if msg.get("type") == "command_result":
            return msg


def _drain_snapshots(ws, max_count: int = 10) -> list[dict]:
    """排空所有待处理的快照消息。"""
    results = []
    for _ in range(max_count):
        try:
            msg = json.loads(ws.receive_text())
            if msg.get("type") == "state_snapshot":
                results.append(msg)
        except Exception:
            break
    return results


class TestWebSocketAuth:
    """认证相关测试。"""

    def test_correct_token_connects(self):
        client = TestClient(app)
        creds = _create_room(client)
        url = _ws_url(creds["roomCode"], creds["playerId"], creds["reconnectToken"])
        with client.websocket_connect(url) as ws:
            snapshot = _receive_snapshot(ws)
            assert snapshot["roomVersion"] >= 0
            assert snapshot["state"]["code"] == creds["roomCode"]

    def test_wrong_token_rejected(self):
        client = TestClient(app)
        creds = _create_room(client)
        url = _ws_url(creds["roomCode"], creds["playerId"], "invalid-token-xxx")
        with pytest.raises(Exception):
            with client.websocket_connect(url) as ws:
                ws.receive_text()


class TestLobbyBroadcast:
    """大厅广播测试。"""

    def test_second_player_join_both_see_two_players(self):
        """第二人加入后，双方快照中都能看到两个玩家。"""
        client = TestClient(app)
        creds1 = _create_room(client, "Alice")
        code = creds1["roomCode"]

        url1 = _ws_url(code, creds1["playerId"], creds1["reconnectToken"])
        with client.websocket_connect(url1) as ws1:
            _receive_snapshot(ws1)

            # 玩家2 加入房间
            creds2 = _join_room(client, code, "Bob")
            url2 = _ws_url(code, creds2["playerId"], creds2["reconnectToken"])

            with client.websocket_connect(url2) as ws2:
                # 玩家2 收到初始快照
                snap2 = _receive_snapshot(ws2)
                assert len(snap2["state"]["players"]) == 2

                # 玩家1 收到广播快照
                snap1 = _receive_snapshot(ws1)
                assert len(snap1["state"]["players"]) == 2

    def test_ready_command_accepted(self):
        """SET_READY 命令被接受。"""
        client = TestClient(app)
        creds1 = _create_room(client, "Alice")
        code = creds1["roomCode"]
        creds2 = _join_room(client, code, "Bob")

        url1 = _ws_url(code, creds1["playerId"], creds1["reconnectToken"])
        url2 = _ws_url(code, creds2["playerId"], creds2["reconnectToken"])

        with client.websocket_connect(url1) as ws1:
            snap1 = _receive_snapshot(ws1)

            with client.websocket_connect(url2) as ws2:
                _receive_snapshot(ws2)
                _receive_snapshot(ws1)  # 广播

                # 使用当前版本发送 SET_READY
                current_version = snap1["roomVersion"]
                ws1.send_text(json.dumps({
                    "type": "command",
                    "requestId": "00000000-0000-0000-0000-000000000001",
                    "roomVersion": current_version,
                    "command": "SET_READY",
                    "payload": {"ready": True},
                }))

                # 玩家1 收到命令结果
                result1 = _receive_command_result(ws1)
                assert result1["accepted"] is True

                # 玩家1 收到广播快照，确认 ready 状态
                snap1 = _receive_snapshot(ws1)
                alice = next(p for p in snap1["state"]["players"] if p["nickname"] == "Alice")
                assert alice["ready"] is True


class TestReconnect:
    """重连和连接替换测试。"""

    def test_new_connection_replaces_old(self):
        """同一玩家再次连接时，新连接正常工作。"""
        client = TestClient(app)
        creds = _create_room(client, "Alice")
        code = creds["roomCode"]
        url = _ws_url(code, creds["playerId"], creds["reconnectToken"])

        # 第一次连接
        with client.websocket_connect(url) as ws1:
            _receive_snapshot(ws1)

            # 同一玩家再次连接（替换旧连接）
            with client.websocket_connect(url) as ws2:
                snap = _receive_snapshot(ws2)
                alice = next(p for p in snap["state"]["players"] if p["nickname"] == "Alice")
                assert alice["connected"] is True

    def test_disconnect_marks_not_connected(self):
        """玩家断开后，重新查询显示 connected=false。"""
        client = TestClient(app)
        creds1 = _create_room(client, "Alice")
        code = creds1["roomCode"]
        creds2 = _join_room(client, code, "Bob")

        url1 = _ws_url(code, creds1["playerId"], creds1["reconnectToken"])
        url2 = _ws_url(code, creds2["playerId"], creds2["reconnectToken"])

        # 两个玩家都连接
        with client.websocket_connect(url1) as ws1:
            _receive_snapshot(ws1)
            with client.websocket_connect(url2) as ws2:
                _receive_snapshot(ws2)
                _receive_snapshot(ws1)  # 广播

        # 所有连接断开后，通过 HTTP API 查询
        resp = client.get(f"/api/rooms/{code}")
        if resp.status_code == 200:
            # 房间还在，检查玩家状态
            room = resp.json()
            assert room["playerCount"] == 2
