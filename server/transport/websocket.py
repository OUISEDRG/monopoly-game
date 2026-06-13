"""WebSocket 传输层：认证、消息循环和关闭码。

对应设计规范第 13、14、24 节。
仅接收 JSON 文本，单条上限 16 KiB。
协议/认证失败使用明确关闭码。
生产环境校验 Origin，拒绝未知来源。
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

from server.logging_config import log_command_event, log_security_event, sanitize_player_id
from server.protocol import (
    ClientCommand,
    ErrorCode,
    accepted_result,
    parse_client_command,
    rejected_result,
)
from server.room_manager import RoomError, RoomManager
from server.security import RateLimiter, validate_origin

logger = logging.getLogger(__name__)

# WebSocket 关闭码（自定义范围 4000-4999）
_CLOSE_AUTH_FAILED = 4001
_CLOSE_INVALID_MESSAGE = 4002
_CLOSE_RATE_LIMITED = 4003
_CLOSE_ORIGIN_BLOCKED = 4004
_CLOSE_INTERNAL_ERROR = 4099

_MAX_MESSAGE_BYTES = 16 * 1024  # 16 KiB
_RATE_LIMIT_PER_SECOND = 10

# 全局限流器
_rate_limiter = RateLimiter(max_per_second=_RATE_LIMIT_PER_SECOND)


async def websocket_endpoint(
    websocket: WebSocket,
    code: str,
    manager: RoomManager,
) -> None:
    """WebSocket 端点 `/ws/rooms/{code}`。

    查询参数：playerId, token
    认证失败直接关闭，认证成功后进入消息循环。
    生产环境校验 Origin，拒绝未知来源。
    """
    # Origin 安全检查（在 accept 之前检查）
    origin = websocket.headers.get("origin")
    if not validate_origin(origin):
        log_security_event(
            logger, "origin_blocked",
            room_code=code,
            reason=f"origin={origin}"
        )
        # 注意：必须先 accept 才能发送 close
        await websocket.accept()
        await websocket.close(code=_CLOSE_ORIGIN_BLOCKED, reason="origin not allowed")
        return

    # 接受连接（必须先 accept 才能收发）
    await websocket.accept()

    # 从查询参数提取认证信息
    player_id_str = websocket.query_params.get("playerId")
    token = websocket.query_params.get("token")

    if not player_id_str or not token:
        await websocket.close(code=_CLOSE_AUTH_FAILED, reason="missing credentials")
        return

    try:
        player_id = UUID(player_id_str)
    except ValueError:
        await websocket.close(code=_CLOSE_AUTH_FAILED, reason="invalid playerId")
        return

    # 认证
    try:
        room_state = await manager.connect(code, player_id, token, websocket)
    except RoomError as e:
        await websocket.close(code=_CLOSE_AUTH_FAILED, reason="auth failed")
        return
    except Exception:
        await websocket.close(code=_CLOSE_INTERNAL_ERROR, reason="internal error")
        return

    # 发送初始完整快照给新连接的玩家
    from server.models.room import build_public_snapshot
    import time

    server_time_ms = int(time.time() * 1000)
    initial_snapshot = build_public_snapshot(room_state, server_time_ms)
    await websocket.send_text(json.dumps(initial_snapshot, ensure_ascii=False))

    # 广播给其他已连接客户端（通知有新玩家连接），排除新玩家自己
    try:
        await manager.broadcast_snapshot(code, exclude_player_id=player_id)
    except RoomError:
        pass

    # 消息循环
    try:
        while True:
            raw_text = await websocket.receive_text()

            # 大小检查
            if len(raw_text.encode("utf-8")) > _MAX_MESSAGE_BYTES:
                log_security_event(
                    logger, "message_too_large",
                    room_code=code, player_id=str(player_id),
                    reason=f"size={len(raw_text.encode('utf-8'))}"
                )
                await websocket.close(
                    code=_CLOSE_INVALID_MESSAGE, reason="message too large"
                )
                return

            # 限流检查
            if not _rate_limiter.check(player_id):
                log_security_event(
                    logger, "rate_limited",
                    room_code=code, player_id=str(player_id)
                )
                await websocket.close(
                    code=_CLOSE_RATE_LIMITED, reason="rate limited"
                )
                return

            # 解析命令
            try:
                cmd = parse_client_command(raw_text)
            except ValueError as e:
                err_msg = str(e)
                if err_msg.startswith("INVALID_COMMAND"):
                    log_command_event(
                        logger, "command_rejected",
                        room_code=code, player_id=str(player_id),
                        request_id="00000000", room_version=0,
                        command="unknown", result="rejected",
                        error_code="INVALID_COMMAND"
                    )
                    # 发送拒绝响应
                    await websocket.send_text(json.dumps(rejected_result(
                        request_id=UUID("00000000-0000-0000-0000-000000000000"),
                        room_version=0,
                        code=ErrorCode.INVALID_COMMAND,
                        message="未知命令",
                    ), ensure_ascii=False))
                    continue
                else:
                    log_command_event(
                        logger, "command_rejected",
                        room_code=code, player_id=str(player_id),
                        request_id="00000000", room_version=0,
                        command="invalid", result="rejected",
                        error_code="INVALID_MESSAGE"
                    )
                    await websocket.send_text(json.dumps(rejected_result(
                        request_id=UUID("00000000-0000-0000-0000-000000000000"),
                        room_version=0,
                        code=ErrorCode.INVALID_MESSAGE,
                        message="消息格式错误",
                    ), ensure_ascii=False))
                    continue

            # 处理命令
            try:
                await _handle_command(manager, code, player_id, cmd, websocket)
            except RoomError as e:
                log_command_event(
                    logger, "command_rejected",
                    room_code=code, player_id=str(player_id),
                    request_id=str(cmd.request_id), room_version=cmd.room_version,
                    command=cmd.command.value, result="rejected",
                    error_code=e.code.value
                )
                await websocket.send_text(json.dumps(rejected_result(
                    request_id=cmd.request_id,
                    room_version=0,
                    code=e.code,
                    message=e.args[0],
                ), ensure_ascii=False))
            except Exception:
                logger.exception("Error handling command")
                await websocket.send_text(json.dumps(rejected_result(
                    request_id=cmd.request_id,
                    room_version=0,
                    code=ErrorCode.INVALID_MESSAGE,
                    message="内部错误",
                ), ensure_ascii=False))

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        try:
            await manager.disconnect(code, player_id)
        except Exception:
            pass


async def _handle_command(
    manager: RoomManager,
    code: str,
    player_id: UUID,
    cmd: ClientCommand,
    websocket: WebSocket,
) -> None:
    """处理解析后的命令，发送结果并广播快照。"""
    # 大厅阶段命令
    if cmd.command.value in ("SET_READY", "START_GAME", "LEAVE_ROOM"):
        updated_room = await manager.handle_command(code, player_id, cmd.command.value, cmd.payload)

        # 发送接受结果
        if updated_room is not None:
            log_command_event(
                logger, "command_accepted",
                room_code=code, player_id=str(player_id),
                request_id=str(cmd.request_id), room_version=updated_room.version,
                command=cmd.command.value, result="accepted"
            )
            await websocket.send_text(json.dumps(accepted_result(
                request_id=cmd.request_id,
                room_version=updated_room.version,
            ), ensure_ascii=False))
            # 在锁外广播快照给所有客户端
            await manager.broadcast_snapshot(code)
        else:
            # LEAVE_ROOM 或无变化
            try:
                room = await manager.get_room_state(code)
                log_command_event(
                    logger, "command_accepted",
                    room_code=code, player_id=str(player_id),
                    request_id=str(cmd.request_id), room_version=room.version,
                    command=cmd.command.value, result="accepted"
                )
                await websocket.send_text(json.dumps(accepted_result(
                    request_id=cmd.request_id,
                    room_version=room.version,
                ), ensure_ascii=False))
            except RoomError:
                # 房间已销毁
                log_command_event(
                    logger, "command_accepted",
                    room_code=code, player_id=str(player_id),
                    request_id=str(cmd.request_id), room_version=0,
                    command=cmd.command.value, result="accepted"
                )
                await websocket.send_text(json.dumps(accepted_result(
                    request_id=cmd.request_id,
                    room_version=0,
                ), ensure_ascii=False))
    else:
        # 游戏阶段命令：使用命令管线处理
        try:
            new_version, events, private_events = await manager.execute_game_command(
                code=code,
                player_id=player_id,
                request_id=cmd.request_id,
                room_version=cmd.room_version,
                command=cmd.command,
                payload=cmd.payload,
            )

            log_command_event(
                logger, "command_accepted",
                room_code=code, player_id=str(player_id),
                request_id=str(cmd.request_id), room_version=new_version,
                command=cmd.command.value, result="accepted"
            )

            # 发送接受结果
            await websocket.send_text(json.dumps(accepted_result(
                request_id=cmd.request_id,
                room_version=new_version,
            ), ensure_ascii=False))

            # 广播快照给所有客户端
            await manager.broadcast_snapshot(code)

            # 发送私密事件给目标玩家
            if private_events:
                await manager.send_private_events(code, private_events)

        except RoomError as e:
            # 版本过期或重复请求
            log_command_event(
                logger, "command_rejected",
                room_code=code, player_id=str(player_id),
                request_id=str(cmd.request_id), room_version=cmd.room_version,
                command=cmd.command.value, result="rejected",
                error_code=e.code.value
            )
            await websocket.send_text(json.dumps(rejected_result(
                request_id=cmd.request_id,
                room_version=0,
                code=e.code,
                message=e.args[0],
            ), ensure_ascii=False))
        except Exception:
            logger.exception("Error executing game command")
            await websocket.send_text(json.dumps(rejected_result(
                request_id=cmd.request_id,
                room_version=0,
                code=ErrorCode.INVALID_MESSAGE,
                message="内部错误",
            ), ensure_ascii=False))
