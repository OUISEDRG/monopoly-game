"""Task 5 测试：HTTP 大厅 API。

覆盖 /、/healthz、创建房间、加入房间、查询不存在房间、
查询大厅房间、查询已开始房间、领域错误映射和请求校验。
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from server.app import app, reset_room_manager


HTTP_RATE_LIMIT = 20


@pytest.fixture(autouse=True)
def _reset():
    """每个测试前重置房间管理器，防止状态串扰。"""
    reset_room_manager()
    yield
    reset_room_manager()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _run_async(coro):
    """在同步测试中运行异步协程。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 基础路由
# ---------------------------------------------------------------------------


class TestHealthz:
    def test_returns_ok(self, client: TestClient):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestIndex:
    def test_returns_html(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# POST /api/rooms — 创建房间
# ---------------------------------------------------------------------------


class TestCreateRoom:
    def test_success(self, client: TestClient):
        resp = client.post("/api/rooms", json={"nickname": "Alice"})
        assert resp.status_code == 200
        data = resp.json()
        assert "roomCode" in data
        assert "playerId" in data
        assert "reconnectToken" in data
        assert "websocketPath" in data
        assert data["websocketPath"] == f"/ws/rooms/{data['roomCode']}"
        assert len(data["roomCode"]) == 6

    def test_empty_nickname_422(self, client: TestClient):
        resp = client.post("/api/rooms", json={"nickname": ""})
        assert resp.status_code == 422

    def test_whitespace_nickname_422(self, client: TestClient):
        resp = client.post("/api/rooms", json={"nickname": "   "})
        assert resp.status_code == 422

    def test_too_long_nickname_422(self, client: TestClient):
        resp = client.post("/api/rooms", json={"nickname": "A" * 13})
        assert resp.status_code == 422

    def test_non_string_nickname_422(self, client: TestClient):
        resp = client.post("/api/rooms", json={"nickname": 123})
        assert resp.status_code == 422

    def test_extra_fields_422(self, client: TestClient):
        resp = client.post("/api/rooms", json={"nickname": "Alice", "extra": "bad"})
        assert resp.status_code == 422

    def test_missing_nickname_422(self, client: TestClient):
        resp = client.post("/api/rooms", json={})
        assert resp.status_code == 422

    def test_rate_limited_after_burst(self, client: TestClient):
        responses = [
            client.post("/api/rooms", json={"nickname": f"P{i:02d}"})
            for i in range(HTTP_RATE_LIMIT + 1)
        ]

        assert [resp.status_code for resp in responses[:HTTP_RATE_LIMIT]] == [
            200
        ] * HTTP_RATE_LIMIT
        assert responses[-1].status_code == 429
        assert responses[-1].json()["detail"]["code"] == "RATE_LIMITED"
        assert "token" not in str(responses[-1].json()).lower()


# ---------------------------------------------------------------------------
# POST /api/rooms/{code}/join — 加入房间
# ---------------------------------------------------------------------------


class TestJoinRoom:
    def test_success(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        resp = client.post(f"/api/rooms/{code}/join", json={"nickname": "Bob"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["roomCode"] == code
        assert "playerId" in data
        assert "reconnectToken" in data
        assert data["websocketPath"] == f"/ws/rooms/{code}"

    def test_not_found_404(self, client: TestClient):
        resp = client.post("/api/rooms/ZZZZZZ/join", json={"nickname": "Bob"})
        assert resp.status_code == 404

    def test_room_full_409(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "P1"})
        code = create.json()["roomCode"]
        for i in range(3):
            client.post(f"/api/rooms/{code}/join", json={"nickname": f"P{i+2}"})
        resp = client.post(f"/api/rooms/{code}/join", json={"nickname": "P5"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "ROOM_FULL"

    def test_already_started_409(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        alice_id = create.json()["playerId"]
        join_resp = client.post(f"/api/rooms/{code}/join", json={"nickname": "Bob"})
        bob_id = join_resp.json()["playerId"]
        from server.app import get_room_manager
        mgr = get_room_manager()
        _run_async(mgr.set_ready(code, UUID(alice_id), True))
        _run_async(mgr.set_ready(code, UUID(bob_id), True))
        _run_async(mgr.start_game(code, UUID(alice_id)))
        resp = client.post(f"/api/rooms/{code}/join", json={"nickname": "Charlie"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "ROOM_ALREADY_STARTED"

    def test_nickname_taken_409(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        resp = client.post(f"/api/rooms/{code}/join", json={"nickname": "ALICE"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "NICKNAME_TAKEN"

    def test_invalid_nickname_422(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        resp = client.post(f"/api/rooms/{code}/join", json={"nickname": ""})
        assert resp.status_code == 422

    def test_code_case_insensitive(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        resp = client.post(f"/api/rooms/{code.lower()}/join", json={"nickname": "Bob"})
        assert resp.status_code == 200

    def test_rate_limited_before_room_lookup_after_burst(self, client: TestClient):
        responses = [
            client.post("/api/rooms/ZZZZZZ/join", json={"nickname": f"J{i:02d}"})
            for i in range(HTTP_RATE_LIMIT + 1)
        ]

        assert [resp.status_code for resp in responses[:HTTP_RATE_LIMIT]] == [
            404
        ] * HTTP_RATE_LIMIT
        assert responses[-1].status_code == 429
        assert responses[-1].json()["detail"]["code"] == "RATE_LIMITED"
        assert "token" not in str(responses[-1].json()).lower()


# ---------------------------------------------------------------------------
# GET /api/rooms/{code} — 查询房间
# ---------------------------------------------------------------------------


class TestGetRoom:
    def test_lobby_room(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        resp = client.get(f"/api/rooms/{code}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["roomCode"] == code
        assert data["phase"] == "lobby"
        assert data["playerCount"] == 1
        assert data["maxPlayers"] == 4
        assert data["joinable"] is True
        # 不得暴露敏感字段
        assert "playerId" not in data
        assert "nickname" not in data
        assert "reconnectToken" not in data
        assert "token" not in str(data).lower()
        assert "digest" not in str(data).lower()

    def test_not_found_404(self, client: TestClient):
        resp = client.get("/api/rooms/ZZZZZZ")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ROOM_NOT_FOUND"

    def test_started_room_not_joinable(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        alice_id = create.json()["playerId"]
        join_resp = client.post(f"/api/rooms/{code}/join", json={"nickname": "Bob"})
        bob_id = join_resp.json()["playerId"]
        from server.app import get_room_manager
        mgr = get_room_manager()
        _run_async(mgr.set_ready(code, UUID(alice_id), True))
        _run_async(mgr.set_ready(code, UUID(bob_id), True))
        _run_async(mgr.start_game(code, UUID(alice_id)))
        resp = client.get(f"/api/rooms/{code}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "playing"
        assert data["joinable"] is False

    def test_full_room_not_joinable(self, client: TestClient):
        create = client.post("/api/rooms", json={"nickname": "P1"})
        code = create.json()["roomCode"]
        for i in range(3):
            client.post(f"/api/rooms/{code}/join", json={"nickname": f"P{i+2}"})
        resp = client.get(f"/api/rooms/{code}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["playerCount"] == 4
        assert data["joinable"] is False


# ---------------------------------------------------------------------------
# 错误响应格式
# ---------------------------------------------------------------------------


class TestErrorFormat:
    def test_error_has_code_and_message(self, client: TestClient):
        resp = client.get("/api/rooms/ZZZZZZ")
        data = resp.json()
        assert "detail" in data
        assert "code" in data["detail"]
        assert "message" in data["detail"]
        assert data["detail"]["code"] == "ROOM_NOT_FOUND"

    def test_422_error_has_code(self, client: TestClient):
        resp = client.post("/api/rooms", json={"nickname": ""})
        data = resp.json()
        assert "code" in data
        assert data["code"] == "VALIDATION_ERROR"

    def test_token_not_in_error_message(self, client: TestClient):
        """错误消息不得包含令牌。"""
        create = client.post("/api/rooms", json={"nickname": "Alice"})
        code = create.json()["roomCode"]
        resp = client.post(f"/api/rooms/{code}/join", json={"nickname": "ALICE"})
        data = resp.json()
        assert "token" not in str(data).lower()
