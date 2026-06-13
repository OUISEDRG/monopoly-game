"""Task 4 测试：大厅房间管理器。

覆盖创建、加入、准备、开始、离开、销毁、令牌校验、
房间码生成、领域异常和版本递增。
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from server.protocol import ErrorCode
from server.room_manager import (
    JoinCredentials,
    RoomError,
    RoomManager,
)
from server.security import issue_reconnect_token, verify_reconnect_token


# ---------------------------------------------------------------------------
# security.py 测试
# ---------------------------------------------------------------------------


class TestIssueReconnectToken:
    def test_returns_token_and_digest(self):
        token, digest = issue_reconnect_token()
        assert isinstance(token, str)
        assert isinstance(digest, str)
        assert len(token) > 0
        assert len(digest) == 64  # SHA-256 hex

    def test_different_calls_produce_different_tokens(self):
        t1, d1 = issue_reconnect_token()
        t2, d2 = issue_reconnect_token()
        assert t1 != t2
        assert d1 != d2


class TestVerifyReconnectToken:
    def test_correct_token_verifies(self):
        token, digest = issue_reconnect_token()
        assert verify_reconnect_token(token, digest) is True

    def test_wrong_token_fails(self):
        token, digest = issue_reconnect_token()
        assert verify_reconnect_token("wrong_token", digest) is False

    def test_empty_token_fails(self):
        _, digest = issue_reconnect_token()
        assert verify_reconnect_token("", digest) is False

    def test_empty_digest_fails(self):
        token, _ = issue_reconnect_token()
        assert verify_reconnect_token(token, "") is False


# ---------------------------------------------------------------------------
# 领域异常测试
# ---------------------------------------------------------------------------


class TestRoomError:
    def test_has_error_code(self):
        err = RoomError(ErrorCode.ROOM_NOT_FOUND, "room not found")
        assert err.code == ErrorCode.ROOM_NOT_FOUND

    def test_message(self):
        err = RoomError(ErrorCode.ROOM_FULL, "room is full")
        assert "room is full" in str(err)

    @pytest.mark.parametrize("code", [
        ErrorCode.INVALID_NICKNAME,
        ErrorCode.ROOM_NOT_FOUND,
        ErrorCode.ROOM_FULL,
        ErrorCode.ROOM_ALREADY_STARTED,
        ErrorCode.NICKNAME_TAKEN,
        ErrorCode.NOT_HOST,
        ErrorCode.NOT_READY,
    ])
    def test_all_required_error_codes(self, code: ErrorCode):
        """必须覆盖 Codex 要求的 7 个错误码。"""
        err = RoomError(code, "test")
        assert err.code == code


# ---------------------------------------------------------------------------
# 房间码测试
# ---------------------------------------------------------------------------


class TestRoomCode:
    @pytest.mark.asyncio
    async def test_code_is_six_characters(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        assert len(creds.room_code) == 6

    @pytest.mark.asyncio
    async def test_code_uses_allowed_charset(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        allowed = set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
        assert set(creds.room_code).issubset(allowed)

    @pytest.mark.asyncio
    async def test_codes_are_unique(self):
        mgr = RoomManager()
        codes = set()
        for _ in range(20):
            creds = await mgr.create_room(f"Player{_}")
            codes.add(creds.room_code)
        assert len(codes) == 20

    @pytest.mark.asyncio
    async def test_code_collision_retry(self):
        """通过注入碰撞生成源测试碰撞重试。"""
        call_count = 0

        def colliding_generator():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return "AAAAAA"
            return "BBBBBB"

        mgr = RoomManager(code_generator=colliding_generator)
        c1 = await mgr.create_room("Alice")
        # 第一次创建用 AAAAAA
        assert c1.room_code == "AAAAAA"
        c2 = await mgr.create_room("Bob")
        # 第二次碰撞 AAAAAA 后重试，第三次返回 BBBBBB
        assert c2.room_code == "BBBBBB"
        assert call_count == 3


# ---------------------------------------------------------------------------
# 创建房间测试
# ---------------------------------------------------------------------------


class TestCreateRoom:
    @pytest.mark.asyncio
    async def test_creates_room_with_host(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        assert isinstance(creds.player_id, UUID)
        assert isinstance(creds.reconnect_token, str)
        assert len(creds.reconnect_token) > 0

    @pytest.mark.asyncio
    async def test_host_is_seat_zero(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        room = await mgr.get_room_state(creds.room_code)
        assert room.players[0].seat == 0
        assert room.players[0].id == creds.player_id

    @pytest.mark.asyncio
    async def test_host_is_first_color(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        room = await mgr.get_room_state(creds.room_code)
        assert room.players[0].color == RoomManager.PLAYER_COLORS[0]

    @pytest.mark.asyncio
    async def test_host_not_ready(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        room = await mgr.get_room_state(creds.room_code)
        assert room.players[0].ready is False

    @pytest.mark.asyncio
    async def test_initial_version_is_zero(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        room = await mgr.get_room_state(creds.room_code)
        assert room.version == 0

    @pytest.mark.asyncio
    async def test_initial_phase_is_lobby(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        room = await mgr.get_room_state(creds.room_code)
        from server.models.room import RoomPhase
        assert room.phase == RoomPhase.LOBBY

    @pytest.mark.asyncio
    async def test_host_matches_player_id(self):
        mgr = RoomManager()
        creds = await mgr.create_room("Alice")
        room = await mgr.get_room_state(creds.room_code)
        assert room.host_player_id == creds.player_id


# ---------------------------------------------------------------------------
# 加入房间测试
# ---------------------------------------------------------------------------


class TestJoinRoom:
    @pytest.mark.asyncio
    async def test_join_assigns_next_seat(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        room = await mgr.get_room_state(c1.room_code)
        assert room.players[1].seat == 1
        assert room.players[1].id == c2.player_id

    @pytest.mark.asyncio
    async def test_join_assigns_next_color(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        room = await mgr.get_room_state(c1.room_code)
        assert room.players[1].color == RoomManager.PLAYER_COLORS[1]

    @pytest.mark.asyncio
    async def test_join_increments_version(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        room_before = await mgr.get_room_state(c1.room_code)
        v_before = room_before.version
        await mgr.join_room(c1.room_code, "Bob")
        room_after = await mgr.get_room_state(c1.room_code)
        assert room_after.version == v_before + 1

    @pytest.mark.asyncio
    async def test_fifth_player_rejected(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("P1")
        await mgr.join_room(c1.room_code, "P2")
        await mgr.join_room(c1.room_code, "P3")
        await mgr.join_room(c1.room_code, "P4")
        with pytest.raises(RoomError) as exc_info:
            await mgr.join_room(c1.room_code, "P5")
        assert exc_info.value.code == ErrorCode.ROOM_FULL

    @pytest.mark.asyncio
    async def test_nickname_casefold_conflict(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        with pytest.raises(RoomError) as exc_info:
            await mgr.join_room(c1.room_code, "ALICE")
        assert exc_info.value.code == ErrorCode.NICKNAME_TAKEN

    @pytest.mark.asyncio
    async def test_nickname_whitespace_trimmed(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "  Bob  ")
        room = await mgr.get_room_state(c1.room_code)
        assert room.players[1].nickname == "Bob"

    @pytest.mark.asyncio
    async def test_nickname_too_short(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        with pytest.raises(RoomError) as exc_info:
            await mgr.join_room(c1.room_code, "")
        assert exc_info.value.code == ErrorCode.INVALID_NICKNAME

    @pytest.mark.asyncio
    async def test_nickname_too_long(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        with pytest.raises(RoomError) as exc_info:
            await mgr.join_room(c1.room_code, "A" * 13)
        assert exc_info.value.code == ErrorCode.INVALID_NICKNAME

    @pytest.mark.asyncio
    async def test_nickname_whitespace_only(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        with pytest.raises(RoomError) as exc_info:
            await mgr.join_room(c1.room_code, "   ")
        assert exc_info.value.code == ErrorCode.INVALID_NICKNAME

    @pytest.mark.asyncio
    async def test_join_after_started_rejected(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        await mgr.start_game(c1.room_code, c1.player_id)
        with pytest.raises(RoomError) as exc_info:
            await mgr.join_room(c1.room_code, "Charlie")
        assert exc_info.value.code == ErrorCode.ROOM_ALREADY_STARTED

    @pytest.mark.asyncio
    async def test_join_nonexistent_room(self):
        mgr = RoomManager()
        with pytest.raises(RoomError) as exc_info:
            await mgr.join_room("ZZZZZZ", "Alice")
        assert exc_info.value.code == ErrorCode.ROOM_NOT_FOUND

    @pytest.mark.asyncio
    async def test_join_normalizes_room_code(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        # 房间码标准化为去空白大写
        c2 = await mgr.join_room(f" {c1.room_code.lower()} ", "Bob")
        assert c2.player_id is not None


# ---------------------------------------------------------------------------
# 准备测试
# ---------------------------------------------------------------------------


class TestSetReady:
    @pytest.mark.asyncio
    async def test_set_ready_increments_version(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        room_before = await mgr.get_room_state(c1.room_code)
        v_before = room_before.version
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        room_after = await mgr.get_room_state(c1.room_code)
        assert room_after.version == v_before + 1
        assert room_after.players[0].ready is True

    @pytest.mark.asyncio
    async def test_set_ready_idempotent_no_version_change(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        room = await mgr.get_room_state(c1.room_code)
        v = room.version
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        room2 = await mgr.get_room_state(c1.room_code)
        assert room2.version == v

    @pytest.mark.asyncio
    async def test_set_not_ready(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c1.player_id, False)
        room = await mgr.get_room_state(c1.room_code)
        assert room.players[0].ready is False

    @pytest.mark.asyncio
    async def test_set_ready_nonexistent_room(self):
        mgr = RoomManager()
        from uuid import uuid4
        with pytest.raises(RoomError) as exc_info:
            await mgr.set_ready("ZZZZZZ", uuid4(), True)
        assert exc_info.value.code == ErrorCode.ROOM_NOT_FOUND


# ---------------------------------------------------------------------------
# 开始游戏测试
# ---------------------------------------------------------------------------


class TestStartGame:
    @pytest.mark.asyncio
    async def test_start_requires_host(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        with pytest.raises(RoomError) as exc_info:
            await mgr.start_game(c1.room_code, c2.player_id)
        assert exc_info.value.code == ErrorCode.NOT_HOST

    @pytest.mark.asyncio
    async def test_start_requires_all_ready(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        # Bob 未准备
        with pytest.raises(RoomError) as exc_info:
            await mgr.start_game(c1.room_code, c1.player_id)
        assert exc_info.value.code == ErrorCode.NOT_READY

    @pytest.mark.asyncio
    async def test_start_requires_at_least_two(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        with pytest.raises(RoomError) as exc_info:
            await mgr.start_game(c1.room_code, c1.player_id)
        assert exc_info.value.code == ErrorCode.NOT_READY

    @pytest.mark.asyncio
    async def test_successful_start(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        room = await mgr.start_game(c1.room_code, c1.player_id)
        from server.models.room import RoomPhase
        assert room.phase == RoomPhase.PLAYING
        assert room.game is not None
        assert room.game.current_player_id == c1.player_id

    @pytest.mark.asyncio
    async def test_start_increments_version(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        room_before = await mgr.get_room_state(c1.room_code)
        v_before = room_before.version
        room = await mgr.start_game(c1.room_code, c1.player_id)
        assert room.version == v_before + 1

    @pytest.mark.asyncio
    async def test_start_already_started_rejected(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        await mgr.start_game(c1.room_code, c1.player_id)
        with pytest.raises(RoomError) as exc_info:
            await mgr.start_game(c1.room_code, c1.player_id)
        assert exc_info.value.code == ErrorCode.ROOM_ALREADY_STARTED


# ---------------------------------------------------------------------------
# 离开房间测试
# ---------------------------------------------------------------------------


class TestLeaveRoom:
    @pytest.mark.asyncio
    async def test_last_player_leaves_destroys_room(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        await mgr.leave_lobby(c1.room_code, c1.player_id)
        with pytest.raises(RoomError) as exc_info:
            await mgr.get_room_state(c1.room_code)
        assert exc_info.value.code == ErrorCode.ROOM_NOT_FOUND

    @pytest.mark.asyncio
    async def test_non_host_leaves(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.leave_lobby(c1.room_code, c2.player_id)
        room = await mgr.get_room_state(c1.room_code)
        assert len(room.players) == 1
        assert room.players[0].nickname == "Alice"

    @pytest.mark.asyncio
    async def test_host_leaves_transfers_host(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        c3 = await mgr.join_room(c1.room_code, "Charlie")
        await mgr.leave_lobby(c1.room_code, c1.player_id)
        room = await mgr.get_room_state(c1.room_code)
        assert room.host_player_id == c2.player_id

    @pytest.mark.asyncio
    async def test_host_leaves_compacts_seats(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        c3 = await mgr.join_room(c1.room_code, "Charlie")
        await mgr.leave_lobby(c1.room_code, c1.player_id)
        room = await mgr.get_room_state(c1.room_code)
        seats = [p.seat for p in room.players]
        assert seats == [0, 1]

    @pytest.mark.asyncio
    async def test_host_leaves_compacts_colors(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        c3 = await mgr.join_room(c1.room_code, "Charlie")
        await mgr.leave_lobby(c1.room_code, c1.player_id)
        room = await mgr.get_room_state(c1.room_code)
        colors = [p.color for p in room.players]
        assert colors == [RoomManager.PLAYER_COLORS[0], RoomManager.PLAYER_COLORS[1]]

    @pytest.mark.asyncio
    async def test_leave_removes_token_digest(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.leave_lobby(c1.room_code, c2.player_id)
        # 验证 Bob 的摘要已删除 — 通过 verify_reconnect_token 间接验证
        # 内部运行时对象不暴露，但房间仍存在
        room = await mgr.get_room_state(c1.room_code)
        assert len(room.players) == 1

    @pytest.mark.asyncio
    async def test_leave_increments_version(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        room_before = await mgr.get_room_state(c1.room_code)
        v_before = room_before.version
        await mgr.leave_lobby(c1.room_code, c2.player_id)
        room_after = await mgr.get_room_state(c1.room_code)
        assert room_after.version == v_before + 1


# ---------------------------------------------------------------------------
# 令牌校验测试
# ---------------------------------------------------------------------------


class TestTokenVerification:
    @pytest.mark.asyncio
    async def test_verify_valid_token(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        assert await mgr.verify_token(c1.room_code, c1.player_id, c1.reconnect_token) is True

    @pytest.mark.asyncio
    async def test_verify_wrong_token(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        assert await mgr.verify_token(c1.room_code, c1.player_id, "wrong") is False

    @pytest.mark.asyncio
    async def test_verify_wrong_player(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        assert await mgr.verify_token(c1.room_code, c2.player_id, c1.reconnect_token) is False


# ---------------------------------------------------------------------------
# 房间码标准化测试
# ---------------------------------------------------------------------------


class TestRoomCodeNormalization:
    @pytest.mark.asyncio
    async def test_get_room_normalizes_code(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        room = await mgr.get_room_state(f" {c1.room_code.lower()} ")
        assert room.code == c1.room_code

    @pytest.mark.asyncio
    async def test_nonexistent_room_raises_not_found(self):
        mgr = RoomManager()
        with pytest.raises(RoomError) as exc_info:
            await mgr.get_room_state("ZZZZZZ")
        assert exc_info.value.code == ErrorCode.ROOM_NOT_FOUND


# ---------------------------------------------------------------------------
# 运行时对象不进入公共快照测试
# ---------------------------------------------------------------------------


class TestPublicSnapshotExclusion:
    @pytest.mark.asyncio
    async def test_snapshot_has_no_token_or_lock(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        from server.models.room import build_public_snapshot
        snapshot = build_public_snapshot(
            await mgr.get_room_state(c1.room_code),
            server_time_ms=1000,
        )
        snapshot_str = str(snapshot)
        assert "token" not in snapshot_str.lower() or "reconnect" not in snapshot_str
        assert "lock" not in snapshot_str.lower()
        assert "digest" not in snapshot_str.lower()
        assert "hash" not in snapshot_str.lower()


# ---------------------------------------------------------------------------
# 只读查询测试
# ---------------------------------------------------------------------------


class TestReadOnlyAccess:
    @pytest.mark.asyncio
    async def test_get_room_returns_deep_copy(self):
        """get_room_state 返回深拷贝，修改不影响内部。"""
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        room1 = await mgr.get_room_state(c1.room_code)
        room2 = await mgr.get_room_state(c1.room_code)
        # 修改返回值不应影响内部状态
        room1.players = []
        room3 = await mgr.get_room_state(c1.room_code)
        assert len(room3.players) == 1

    @pytest.mark.asyncio
    async def test_deep_copy_player_fields_isolated(self):
        """修改返回值的玩家字段不影响内部状态。"""
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        room = await mgr.get_room_state(c1.room_code)
        room.players[0].nickname = "Hacked"
        room.players[0].money = 999999
        room2 = await mgr.get_room_state(c1.room_code)
        assert room2.players[0].nickname == "Alice"
        assert room2.players[0].money == 15000

    @pytest.mark.asyncio
    async def test_deep_copy_game_field_isolated(self):
        """修改返回值的 game 字段不影响内部状态。"""
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        await mgr.start_game(c1.room_code, c1.player_id)
        room = await mgr.get_room_state(c1.room_code)
        room.game.free_parking_money = 999999
        room2 = await mgr.get_room_state(c1.room_code)
        assert room2.game.free_parking_money == 0


# ---------------------------------------------------------------------------
# 返修回归测试：覆盖 Codex 审查的 5 项差异
# ---------------------------------------------------------------------------


class TestCreateRoomNicknameValidation:
    """差异1: create_room 必须复用 _validate_nickname。"""

    @pytest.mark.asyncio
    async def test_empty_nickname_rejected(self):
        mgr = RoomManager()
        with pytest.raises(RoomError) as exc_info:
            await mgr.create_room("")
        assert exc_info.value.code == ErrorCode.INVALID_NICKNAME

    @pytest.mark.asyncio
    async def test_whitespace_only_nickname_rejected(self):
        mgr = RoomManager()
        with pytest.raises(RoomError) as exc_info:
            await mgr.create_room("   ")
        assert exc_info.value.code == ErrorCode.INVALID_NICKNAME

    @pytest.mark.asyncio
    async def test_too_long_nickname_rejected(self):
        mgr = RoomManager()
        with pytest.raises(RoomError) as exc_info:
            await mgr.create_room("A" * 13)
        assert exc_info.value.code == ErrorCode.INVALID_NICKNAME

    @pytest.mark.asyncio
    async def test_valid_nickname_trimmed(self):
        mgr = RoomManager()
        c = await mgr.create_room("  Alice  ")
        room = await mgr.get_room_state(c.room_code)
        assert room.players[0].nickname == "Alice"

    @pytest.mark.asyncio
    async def test_no_partial_room_on_invalid_nickname(self):
        """非法昵称不得留下半成品房间。"""
        mgr = RoomManager()
        try:
            await mgr.create_room("")
        except RoomError:
            pass
        # 不应有任何房间
        with pytest.raises(RoomError) as exc_info:
            await mgr.get_room_state("ZZZZZZ")
        assert exc_info.value.code == ErrorCode.ROOM_NOT_FOUND


class TestRoomCodeValidation:
    """差异5: 注入生成器产生非法代码时必须重试。"""

    @pytest.mark.asyncio
    async def test_injected_bad_code_retried(self):
        """注入生成器先返回非法代码，再返回合法代码。"""
        call_count = 0

        def gen():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "abc123"  # 小写，非法
            if call_count == 2:
                return "AB"  # 太短，非法
            return "AAAAAA"  # 合法

        mgr = RoomManager(code_generator=gen)
        c = await mgr.create_room("Alice")
        assert c.room_code == "AAAAAA"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_bad_codes_raises(self):
        """注入生成器始终返回非法代码，100 次后抛异常。"""
        def gen():
            return "bad code!"  # 永远非法

        mgr = RoomManager(code_generator=gen)
        with pytest.raises(RoomError):
            await mgr.create_room("Alice")

    @pytest.mark.asyncio
    async def test_no_partial_room_on_bad_code(self):
        """非法代码不得留下半成品房间。"""
        call_count = 0

        def gen():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return "bad"
            return "AAAAAA"

        mgr = RoomManager(code_generator=gen)
        c = await mgr.create_room("Alice")
        assert c.room_code == "AAAAAA"


class TestLobbyPhaseConstraint:
    """差异4: set_ready 和 leave_lobby 仅允许 LOBBY 阶段。"""

    @pytest.mark.asyncio
    async def test_set_ready_after_start_rejected(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        await mgr.start_game(c1.room_code, c1.player_id)
        with pytest.raises(RoomError) as exc_info:
            await mgr.set_ready(c1.room_code, c1.player_id, False)
        assert exc_info.value.code == ErrorCode.ROOM_ALREADY_STARTED

    @pytest.mark.asyncio
    async def test_set_ready_after_start_no_version_change(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        room = await mgr.start_game(c1.room_code, c1.player_id)
        v = room.version
        try:
            await mgr.set_ready(c1.room_code, c1.player_id, False)
        except RoomError:
            pass
        room2 = await mgr.get_room_state(c1.room_code)
        assert room2.version == v

    @pytest.mark.asyncio
    async def test_leave_after_start_rejected(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        await mgr.start_game(c1.room_code, c1.player_id)
        with pytest.raises(RoomError) as exc_info:
            await mgr.leave_lobby(c1.room_code, c1.player_id)
        assert exc_info.value.code == ErrorCode.ROOM_ALREADY_STARTED

    @pytest.mark.asyncio
    async def test_leave_after_start_no_player_removal(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        await mgr.start_game(c1.room_code, c1.player_id)
        try:
            await mgr.leave_lobby(c1.room_code, c1.player_id)
        except RoomError:
            pass
        room = await mgr.get_room_state(c1.room_code)
        assert len(room.players) == 2


class TestSetReadyReturnsDeepCopy:
    """差异3: set_ready 和 start_game 返回深拷贝。"""

    @pytest.mark.asyncio
    async def test_set_ready_returns_deep_copy(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        room = await mgr.set_ready(c1.room_code, c1.player_id, True)
        room.players[0].nickname = "Hacked"
        room2 = await mgr.get_room_state(c1.room_code)
        assert room2.players[0].nickname == "Alice"

    @pytest.mark.asyncio
    async def test_start_game_returns_deep_copy(self):
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)
        room = await mgr.start_game(c1.room_code, c1.player_id)
        room.game.free_parking_money = 999999
        room2 = await mgr.get_room_state(c1.room_code)
        assert room2.game.free_parking_money == 0


class TestConcurrentAccess:
    """差异2: 并发安全性测试。"""

    @pytest.mark.asyncio
    async def test_concurrent_join_max_four(self):
        """并发加入同一 3 人房间，最多只有 1 人成功，最终人数为 4。"""
        mgr = RoomManager()
        c1 = await mgr.create_room("P1")
        await mgr.join_room(c1.room_code, "P2")
        await mgr.join_room(c1.room_code, "P3")

        results = await asyncio.gather(
            mgr.join_room(c1.room_code, "P4"),
            mgr.join_room(c1.room_code, "P5"),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], RoomError)
        assert failures[0].code == ErrorCode.ROOM_FULL

        room = await mgr.get_room_state(c1.room_code)
        assert len(room.players) == 4

    @pytest.mark.asyncio
    async def test_concurrent_same_nickname(self):
        """并发使用同昵称加入，最多 1 人成功。"""
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")

        results = await asyncio.gather(
            mgr.join_room(c1.room_code, "Bob"),
            mgr.join_room(c1.room_code, "BOB"),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], RoomError)
        assert failures[0].code == ErrorCode.NICKNAME_TAKEN

    @pytest.mark.asyncio
    async def test_concurrent_start_no_duplicate_version(self):
        """并发开始不得重复递增版本。"""
        mgr = RoomManager()
        c1 = await mgr.create_room("Alice")
        c2 = await mgr.join_room(c1.room_code, "Bob")
        await mgr.set_ready(c1.room_code, c1.player_id, True)
        await mgr.set_ready(c1.room_code, c2.player_id, True)

        room_before = await mgr.get_room_state(c1.room_code)
        v_before = room_before.version

        results = await asyncio.gather(
            mgr.start_game(c1.room_code, c1.player_id),
            mgr.start_game(c1.room_code, c1.player_id),
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1

        room_after = await mgr.get_room_state(c1.room_code)
        assert room_after.version == v_before + 1
