"""大厅房间管理器。

对应设计规范第 8、23 节和实施计划 Task 4。
管理房间生命周期：创建、加入、准备、开始、离开和销毁。
每个房间持有私有运行时对象（asyncio.Lock、令牌摘要），
不进入 RoomState 或公共快照。
"""

from __future__ import annotations

import asyncio
import copy
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi import WebSocket

from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState
from server.models.room import RoomPhase, RoomState, build_public_snapshot
from server.protocol import ErrorCode
from server.security import issue_reconnect_token, verify_reconnect_token, sanitize_nickname

# 新增导入
from server.engine.rules import RandomSource, SystemRandomSource, apply_command
from server.engine.commands import EngineResult
from server.engine.timeout_policy import apply_disconnect_timeout, apply_phase_timeout
from server.protocol import CommandName
from server.scheduler import DeadlineConfig


# ---------------------------------------------------------------------------
# 房间码字符集（无歧义：排除 I/O/0/1/L）
# ---------------------------------------------------------------------------

_ROOM_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_ROOM_CODE_LENGTH = 6


# ---------------------------------------------------------------------------
# 领域异常
# ---------------------------------------------------------------------------


class RoomError(Exception):
    """房间领域异常，携带稳定 ErrorCode。"""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# 加入凭证
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JoinCredentials:
    """加入房间后返回的凭证。明文令牌只在此返回一次。"""

    room_code: str
    player_id: UUID
    reconnect_token: str


@dataclass(frozen=True, slots=True)
class TimeoutResult:
    """Result of a scheduler timeout pass for one room."""

    room_code: str
    events: list[dict]
    private_events: dict[UUID, list[dict]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 房间运行时（私有，不进入 RoomState）
# ---------------------------------------------------------------------------


@dataclass
class _RoomRuntime:
    """房间私有运行时对象。"""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    token_digests: dict[UUID, str] = field(default_factory=dict)
    sockets_by_player_id: dict[UUID, WebSocket] = field(default_factory=dict)
    # 幂等缓存：request_id -> (room_version, result_events, private_events)
    idempotency_cache: dict[UUID, tuple[int, list[dict], dict[UUID, list[dict]] | None]] = field(default_factory=dict)
    # 记录当前正在处理的请求（用于并发控制）
    active_requests: set[UUID] = field(default_factory=set)
    # 断线保留期限：player_id -> deadline
    disconnect_deadlines: dict[UUID, datetime] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 房间管理器
# ---------------------------------------------------------------------------


class RoomManager:
    """进程内大厅房间管理器。

    所有公开方法将房间码标准化为去空白大写。
    不暴露内部房间字典或运行时对象。
    写操作在房间锁内完成，返回深拷贝。
    """

    PLAYER_COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12"]
    MAX_PLAYERS = 4

    def __init__(
        self,
        code_generator: object | None = None,
        *,
        deadline_config: DeadlineConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        random_source_factory: Callable[[], RandomSource] | None = None,
    ) -> None:
        self._rooms: dict[str, RoomState] = {}
        self._runtimes: dict[str, _RoomRuntime] = {}
        self._code_generator = code_generator
        self._manager_lock = asyncio.Lock()
        self._deadline_config = deadline_config or DeadlineConfig()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._random_source_factory = random_source_factory or SystemRandomSource

    # ---- 时间与截止时间 ----

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current

    @staticmethod
    def _coerce_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _deadline(now: datetime, seconds: float) -> datetime:
        return now + timedelta(seconds=seconds)

    @staticmethod
    def _find_player(room: RoomState, player_id: UUID) -> PlayerState | None:
        for player in room.players:
            if player.id == player_id:
                return player
        return None

    def _refresh_game_deadlines(
        self,
        room: RoomState,
        now: datetime,
        *,
        previous_turn_deadline: datetime | None = None,
    ) -> None:
        """Set the active deadline for the current game phase."""
        game = room.game
        if game is None:
            return

        if game.phase in (TurnPhase.WAITING_FOR_ROLL, TurnPhase.AWAITING_PROPERTY_DECISION, TurnPhase.AWAITING_CARD_DECISION):
            game.turn_deadline = self._deadline(now, self._deadline_config.turn_seconds)
            return

        if game.phase == TurnPhase.AUCTION:
            game.turn_deadline = None
            if game.auction is not None:
                game.auction.deadline = self._deadline(now, self._deadline_config.auction_seconds)
            return

        if game.phase == TurnPhase.TRADE_NEGOTIATION:
            game.turn_deadline = None
            if game.trade is not None:
                if game.trade.paused_turn_deadline is None:
                    game.trade.paused_turn_deadline = previous_turn_deadline
                game.trade.deadline = self._deadline(now, self._deadline_config.trade_seconds)
            return

        if game.phase == TurnPhase.DEBT_RELIEF:
            game.turn_deadline = None
            if game.debt is not None:
                game.debt.deadline = self._deadline(now, self._deadline_config.turn_seconds)
            return

        if game.phase == TurnPhase.GAME_OVER:
            game.turn_deadline = None
            return

    def _active_game_deadline(self, room: RoomState) -> datetime | None:
        game = room.game
        if game is None:
            return None
        if game.phase == TurnPhase.AUCTION and game.auction is not None:
            return game.auction.deadline
        if game.phase == TurnPhase.TRADE_NEGOTIATION and game.trade is not None:
            return game.trade.deadline
        if game.phase == TurnPhase.DEBT_RELIEF and game.debt is not None:
            return game.debt.deadline
        return game.turn_deadline

    # ---- 房间码生成 ----

    def _generate_code(self) -> str:
        if self._code_generator is not None:
            return self._code_generator()
        return "".join(secrets.choice(_ROOM_CODE_CHARS) for _ in range(_ROOM_CODE_LENGTH))

    @staticmethod
    def _validate_code_format(code: str) -> bool:
        """验证房间码恰好 6 位且仅含无歧义字符。"""
        if len(code) != _ROOM_CODE_LENGTH:
            return False
        allowed = set(_ROOM_CODE_CHARS)
        return all(c in allowed for c in code)

    def _generate_unique_code(self) -> str:
        for _ in range(100):
            code = self._generate_code()
            if not self._validate_code_format(code):
                continue
            if code not in self._rooms:
                return code
        raise RoomError(ErrorCode.INVALID_MESSAGE, "无法生成合法唯一房间码")

    # ---- 房间码标准化 ----

    @staticmethod
    def _normalize_code(code: str) -> str:
        return code.strip().upper()

    # ---- 内部查找 ----

    def _find_room(self, code: str) -> tuple[RoomState, _RoomRuntime]:
        normalized = self._normalize_code(code)
        room = self._rooms.get(normalized)
        if room is None:
            raise RoomError(ErrorCode.ROOM_NOT_FOUND, f"房间 {normalized} 不存在")
        runtime = self._runtimes[normalized]
        return room, runtime

    # ---- 昵称校验 ----

    @staticmethod
    def _validate_nickname(nickname: str, existing_nicknames: list[str]) -> str:
        # 先清理控制字符
        cleaned = sanitize_nickname(nickname)
        if len(cleaned) < 1 or len(cleaned) > 12:
            raise RoomError(ErrorCode.INVALID_NICKNAME, "昵称长度必须为 1–12 个字符")
        for existing in existing_nicknames:
            if cleaned.casefold() == existing.casefold():
                raise RoomError(ErrorCode.NICKNAME_TAKEN, f"昵称 {cleaned} 已被使用")
        return cleaned

    # ---- 深拷贝辅助 ----

    @staticmethod
    def _deep_copy_room(room: RoomState) -> RoomState:
        """返回 RoomState 的深拷贝，防止外部修改内部状态。"""
        return copy.deepcopy(room)

    # ---- 公开接口 ----

    async def create_room(self, nickname: str) -> JoinCredentials:
        """创建房间，创建者成为房主。"""
        # 昵称校验（无已有昵称）
        validated_name = self._validate_nickname(nickname, [])

        # 管理器级锁保护"生成唯一房间码 + 注册房间/运行时"
        async with self._manager_lock:
            code = self._generate_unique_code()
            player_id = uuid4()
            token, digest = issue_reconnect_token()

            player = PlayerState(
                id=player_id,
                nickname=validated_name,
                seat=0,
                color=self.PLAYER_COLORS[0],
                ready=False,
            )

            room = RoomState(
                code=code,
                host_player_id=player_id,
                phase=RoomPhase.LOBBY,
                players=[player],
                version=0,
            )

            runtime = _RoomRuntime()
            runtime.token_digests[player_id] = digest

            self._rooms[code] = room
            self._runtimes[code] = runtime

        return JoinCredentials(
            room_code=code,
            player_id=player_id,
            reconnect_token=token,
        )

    async def join_room(self, code: str, nickname: str) -> JoinCredentials:
        """加入房间。只允许 LOBBY 阶段，最多 4 人。"""
        room, runtime = self._find_room(code)

        async with runtime.lock:
            if room.phase != RoomPhase.LOBBY:
                raise RoomError(ErrorCode.ROOM_ALREADY_STARTED, "游戏已开始，无法加入")

            if len(room.players) >= self.MAX_PLAYERS:
                raise RoomError(ErrorCode.ROOM_FULL, "房间已满")

            existing_names = [p.nickname for p in room.players]
            validated_name = self._validate_nickname(nickname, existing_names)

            player_id = uuid4()
            token, digest = issue_reconnect_token()

            seat = len(room.players)
            color = self.PLAYER_COLORS[seat]

            player = PlayerState(
                id=player_id,
                nickname=validated_name,
                seat=seat,
                color=color,
                ready=False,
            )

            room.players.append(player)
            room.version += 1
            runtime.token_digests[player_id] = digest

        return JoinCredentials(
            room_code=room.code,
            player_id=player_id,
            reconnect_token=token,
        )

    async def set_ready(self, code: str, player_id: UUID, ready: bool) -> RoomState:
        """设置玩家准备状态。只在 LOBBY 阶段，状态实际改变时递增版本。"""
        room, runtime = self._find_room(code)

        async with runtime.lock:
            if room.phase != RoomPhase.LOBBY:
                raise RoomError(ErrorCode.ROOM_ALREADY_STARTED, "游戏已开始，无法修改准备状态")

            player = None
            for p in room.players:
                if p.id == player_id:
                    player = p
                    break

            if player is None:
                raise RoomError(ErrorCode.ROOM_NOT_FOUND, "玩家不在房间中")

            if player.ready == ready:
                return self._deep_copy_room(room)

            player.ready = ready
            room.version += 1
            return self._deep_copy_room(room)

    async def start_game(self, code: str, player_id: UUID) -> RoomState:
        """房主开始游戏。需要 2–4 人且全员准备。"""
        room, runtime = self._find_room(code)

        async with runtime.lock:
            if room.phase != RoomPhase.LOBBY:
                raise RoomError(ErrorCode.ROOM_ALREADY_STARTED, "游戏已开始")

            if room.host_player_id != player_id:
                raise RoomError(ErrorCode.NOT_HOST, "只有房主可以开始游戏")

            if len(room.players) < 2:
                raise RoomError(ErrorCode.NOT_READY, "至少需要 2 名玩家")

            if not all(p.ready for p in room.players):
                raise RoomError(ErrorCode.NOT_READY, "所有玩家必须准备")

            room.phase = RoomPhase.PLAYING
            room.game = GameState(current_player_id=room.players[0].id)
            self._refresh_game_deadlines(room, self._now())
            room.version += 1
            return self._deep_copy_room(room)

    async def leave_lobby(self, code: str, player_id: UUID) -> None:
        """玩家离开大厅。只允许 LOBBY 阶段。最后一人离开时删除房间。"""
        room, runtime = self._find_room(code)

        async with runtime.lock:
            if room.phase != RoomPhase.LOBBY:
                raise RoomError(ErrorCode.ROOM_ALREADY_STARTED, "游戏已开始，无法离开")
            await self._leave_room_locked(room, runtime, player_id)

    async def _leave_room_locked(
        self, room: RoomState, runtime: _RoomRuntime, player_id: UUID
    ) -> None:
        """在锁内执行离开房间逻辑。"""
        # 找到离开的玩家
        leaving_idx = None
        for i, p in enumerate(room.players):
            if p.id == player_id:
                leaving_idx = i
                break

        if leaving_idx is None:
            return

        # 移除玩家和令牌摘要
        room.players.pop(leaving_idx)
        runtime.token_digests.pop(player_id, None)
        runtime.sockets_by_player_id.pop(player_id, None)

        # 最后一人离开 → 删除房间
        if not room.players:
            del self._rooms[room.code]
            del self._runtimes[room.code]
            return

        # 房主离开 → 转交给最低 seat 的剩余玩家
        if room.host_player_id == player_id:
            room.host_player_id = room.players[0].id

        # 压紧 seat 和颜色为确定顺序
        for i, p in enumerate(room.players):
            p.seat = i
            p.color = self.PLAYER_COLORS[i]

        room.version += 1

    async def get_room_state(self, code: str) -> RoomState:
        """只读查询房间状态。在锁内返回深拷贝，不暴露内部引用。"""
        room, runtime = self._find_room(code)

        async with runtime.lock:
            return self._deep_copy_room(room)

    async def verify_token(
        self, code: str, player_id: UUID, token: str
    ) -> bool:
        """校验重连令牌。"""
        try:
            room, runtime = self._find_room(code)
        except RoomError:
            return False

        async with runtime.lock:
            digest = runtime.token_digests.get(player_id)
            if digest is None:
                return False
            return verify_reconnect_token(token, digest)

    # ---- WebSocket 连接管理 ----

    async def connect(
        self, code: str, player_id: UUID, token: str, socket: WebSocket
    ) -> RoomState:
        """验证令牌并注册 WebSocket 连接。

        在锁内完成：验证令牌、替换旧连接、标记 connected。
        返回连接后的房间状态深拷贝。
        调用者负责在锁外发送初始快照和广播。
        """
        room, runtime = self._find_room(code)

        async with runtime.lock:
            # 验证令牌
            digest = runtime.token_digests.get(player_id)
            if digest is None or not verify_reconnect_token(token, digest):
                raise RoomError(ErrorCode.AUTH_FAILED, "认证失败")

            # 查找玩家
            player = None
            for p in room.players:
                if p.id == player_id:
                    player = p
                    break

            if player is None:
                raise RoomError(ErrorCode.ROOM_NOT_FOUND, "玩家不在房间中")

            # 替换旧连接
            old_socket = runtime.sockets_by_player_id.get(player_id)
            if old_socket is not None:
                try:
                    await old_socket.close(code=4000, reason="replaced")
                except Exception:
                    pass

            # 注册新连接
            runtime.sockets_by_player_id[player_id] = socket
            runtime.disconnect_deadlines.pop(player_id, None)
            player.connected = True
            player.disconnected_at = None
            room.version += 1

            return self._deep_copy_room(room)

    async def disconnect(self, code: str, player_id: UUID) -> None:
        """处理 WebSocket 断开。标记玩家断线。"""
        room, runtime = self._find_room(code)

        async with runtime.lock:
            # 移除 socket
            runtime.sockets_by_player_id.pop(player_id, None)

            # 标记玩家断线
            player = None
            for p in room.players:
                if p.id == player_id:
                    player = p
                    break

            if player is not None:
                player.connected = False
                now = self._now()
                player.disconnected_at = now
                if room.phase == RoomPhase.PLAYING:
                    runtime.disconnect_deadlines[player_id] = self._deadline(
                        now, self._deadline_config.disconnect_seconds
                    )
                room.version += 1

            # 大厅中所有连接离开 → 销毁房间
            if room.phase == RoomPhase.LOBBY and not room.players:
                del self._rooms[room.code]
                del self._runtimes[room.code]
                return

        # 锁外广播（如果还有连接）
        try:
            await self.broadcast_snapshot(code)
        except RoomError:
            pass  # 房间已销毁

    async def broadcast_snapshot(
        self, code: str, *, exclude_player_id: UUID | None = None
    ) -> None:
        """手动触发快照广播（用于 HTTP 操作后通知 WebSocket 客户端）。"""
        room, runtime = self._find_room(code)

        async with runtime.lock:
            if runtime.sockets_by_player_id:
                await self._broadcast_snapshot(room, runtime, exclude_player_id=exclude_player_id)

    async def _broadcast_snapshot(
        self, room: RoomState, runtime: _RoomRuntime, *, exclude_player_id: UUID | None = None
    ) -> None:
        """向所有已连接客户端广播完整公共快照。"""
        import time as _time
        server_time_ms = int(_time.time() * 1000)
        snapshot = build_public_snapshot(room, server_time_ms)
        import json as _json
        text = _json.dumps(snapshot, ensure_ascii=False)

        dead_sockets: list[UUID] = []
        for pid, socket in runtime.sockets_by_player_id.items():
            if exclude_player_id is not None and pid == exclude_player_id:
                continue
            try:
                await socket.send_text(text)
            except Exception:
                dead_sockets.append(pid)

        for pid in dead_sockets:
            runtime.sockets_by_player_id.pop(pid, None)

    # ---- WebSocket 命令处理 ----

    async def handle_command(
        self, code: str, player_id: UUID, command: str, payload: dict
    ) -> RoomState | None:
        """处理大厅 WebSocket 命令（SET_READY / START_GAME / LEAVE_ROOM）。

        在锁内执行命令、递增版本。
        返回更新后的房间状态深拷贝（需要广播时），
        或 None（房间已销毁时）。
        调用者负责在锁外广播快照。
        """
        room, runtime = self._find_room(code)

        async with runtime.lock:
            if command == "SET_READY":
                ready = payload.get("ready", True)
                player = None
                for p in room.players:
                    if p.id == player_id:
                        player = p
                        break

                if player is None:
                    return None

                if player.ready != ready:
                    player.ready = ready
                    room.version += 1
                    return self._deep_copy_room(room)

                return None

            elif command == "LEAVE_ROOM":
                await self._leave_room_locked(room, runtime, player_id)
                return None

            elif command == "START_GAME":
                if room.phase != RoomPhase.LOBBY:
                    raise RoomError(ErrorCode.ROOM_ALREADY_STARTED, "游戏已开始")
                if room.host_player_id != player_id:
                    raise RoomError(ErrorCode.NOT_HOST, "只有房主可以开始游戏")
                if len(room.players) < 2:
                    raise RoomError(ErrorCode.NOT_READY, "至少需要 2 名玩家")
                if not all(p.ready for p in room.players):
                    raise RoomError(ErrorCode.NOT_READY, "所有玩家必须准备")
                room.phase = RoomPhase.PLAYING
                room.game = GameState(current_player_id=room.players[0].id)
                self._refresh_game_deadlines(room, self._now())
                room.version += 1
                return self._deep_copy_room(room)

            return None

    # ---- 游戏命令处理 ----

    async def execute_game_command(
        self,
        code: str,
        player_id: UUID,
        request_id: UUID,
        room_version: int,
        command: CommandName,
        payload: dict,
    ) -> tuple[int, list[dict], dict[UUID, list[dict]] | None]:
        """执行游戏引擎命令的完整管线。

        返回：(new_version, events, private_events)
        抛出 RoomError：STALE_STATE（版本过期）、DUPLICATE_REQUEST（重复请求）
        """
        room, runtime = self._find_room(code)

        async with runtime.lock:
            # 1. 幂等检查（重复 request_id）
            if request_id in runtime.idempotency_cache:
                cached_version, cached_events, cached_private_events = runtime.idempotency_cache[request_id]
                return cached_version, cached_events, cached_private_events

            # 2. 版本检查（乐观锁）
            if room_version != room.version:
                raise RoomError(ErrorCode.STALE_STATE, f"版本过期：当前 {room.version}，请求 {room_version}")

            # 3. 并发检查（防止同一请求被处理多次）
            if request_id in runtime.active_requests:
                raise RoomError(ErrorCode.DUPLICATE_REQUEST, "请求正在处理中")

            # 4. 标记请求正在处理
            runtime.active_requests.add(request_id)

            try:
                # 5. 执行引擎命令
                now = self._now()
                previous_turn_deadline = room.game.turn_deadline if room.game is not None else None

                result = apply_command(
                    game=room.game,
                    actor_id=player_id,
                    command=command,
                    payload=payload,
                    random_source=self._random_source_factory(),
                    now=now,
                    players=room.players,
                )

                # 6. 版本管理：只有命令成功改变状态才递增版本
                if result.changed:
                    room.version += 1
                    self._refresh_game_deadlines(
                        room,
                        now,
                        previous_turn_deadline=previous_turn_deadline,
                    )
                    # 7. 缓存幂等结果（包含 private_events）
                    runtime.idempotency_cache[request_id] = (room.version, result.events, result.private_events)
                else:
                    # 拒绝的命令也缓存（防止重复拒绝）
                    runtime.idempotency_cache[request_id] = (room.version, result.events, result.private_events)

                return room.version, result.events, result.private_events
            finally:
                # 8. 清理正在处理标记
                runtime.active_requests.discard(request_id)

    async def process_due_timeouts(self, now: datetime | None = None) -> list[TimeoutResult]:
        """Process every room deadline that is due at ``now``.

        Tests call this directly with an injected clock; the background
        scheduler uses the same method periodically in production.
        """
        current = self._coerce_datetime(now) if now is not None else self._now()
        results: list[TimeoutResult] = []
        codes = list(self._rooms.keys())

        for code in codes:
            try:
                room, runtime = self._find_room(code)
            except RoomError:
                continue

            events: list[dict] = []
            private_events: dict[UUID, list[dict]] = {}

            async with runtime.lock:
                if room.phase != RoomPhase.PLAYING or room.game is None:
                    continue

                # Disconnected players keep their seats until the deadline.
                for player_id, deadline in list(runtime.disconnect_deadlines.items()):
                    player = self._find_player(room, player_id)
                    if player is None or player.connected or player.bankrupt:
                        runtime.disconnect_deadlines.pop(player_id, None)
                        continue
                    if self._coerce_datetime(deadline) <= current:
                        result = apply_disconnect_timeout(
                            room.game,
                            room.players,
                            player_id=player_id,
                        )
                        runtime.disconnect_deadlines.pop(player_id, None)
                        if result.changed:
                            room.version += 1
                            events.extend(result.events)
                            private_events.update(result.private_events)
                            self._refresh_game_deadlines(room, current)

                active_deadline = self._active_game_deadline(room)
                if active_deadline is not None and self._coerce_datetime(active_deadline) <= current:
                    previous_turn_deadline = room.game.turn_deadline
                    result = apply_phase_timeout(
                        room.game,
                        room.players,
                        random_source=self._random_source_factory(),
                        now=current,
                    )
                    if result.changed:
                        room.version += 1
                        events.extend(result.events)
                        private_events.update(result.private_events)
                        self._refresh_game_deadlines(
                            room,
                            current,
                            previous_turn_deadline=previous_turn_deadline,
                        )

            if events:
                results.append(
                    TimeoutResult(
                        room_code=code,
                        events=events,
                        private_events=private_events,
                    )
                )
                if private_events:
                    await self.send_private_events(code, private_events)
                try:
                    await self.broadcast_snapshot(code)
                except RoomError:
                    pass

        return results

    async def send_private_events(
        self, code: str, private_events: dict[UUID, list[dict]], exclude_player_id: UUID | None = None
    ) -> None:
        """发送私密事件给目标玩家。"""
        room, runtime = self._find_room(code)

        import json as _json
        for target_id, events in private_events.items():
            if exclude_player_id is not None and target_id == exclude_player_id:
                continue
            socket = runtime.sockets_by_player_id.get(target_id)
            if socket is not None:
                try:
                    for event in events:
                        await socket.send_text(_json.dumps(event, ensure_ascii=False))
                except Exception:
                    pass
