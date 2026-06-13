"""FastAPI 应用入口。

提供 /healthz、HTTP 大厅 API 和静态文件服务。
持有单一进程内 RoomManager，支持测试间重置。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.logging_config import configure_logging
from server.protocol import ErrorCode
from server.room_manager import RoomError, RoomManager
from server.scheduler import RoomScheduler
from server.security import RateLimiter
from server.transport.websocket import websocket_endpoint

# 配置日志
configure_logging()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 应用与房间管理器
# ---------------------------------------------------------------------------

_room_manager: RoomManager = RoomManager()
_scheduler: RoomScheduler | None = None
_http_rate_limiter = RateLimiter(max_per_second=20)


def get_room_manager() -> RoomManager:
    """返回当前房间管理器实例。"""
    return _room_manager


def reset_room_manager() -> None:
    """重置房间管理器，用于测试间隔离。"""
    global _room_manager, _scheduler
    _room_manager = RoomManager()
    _scheduler = RoomScheduler(_room_manager)
    reset_http_rate_limiter()


def reset_http_rate_limiter() -> None:
    """Clear HTTP create/join rate-limit state between tests."""
    _http_rate_limiter.clear_all()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _scheduler
    _scheduler = RoomScheduler(get_room_manager())
    await _scheduler.start()
    try:
        yield
    finally:
        if _scheduler is not None:
            await _scheduler.stop()


app = FastAPI(title="Online Monopoly", lifespan=lifespan)


# ---------------------------------------------------------------------------
# CORS 配置
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class NicknameRequest(BaseModel):
    """昵称请求，严格校验。禁止额外字段。"""

    model_config = {"extra": "forbid"}

    nickname: str = Field(min_length=1, max_length=12)


# ---------------------------------------------------------------------------
# 错误映射
# ---------------------------------------------------------------------------

_ERROR_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.ROOM_NOT_FOUND: 404,
    ErrorCode.ROOM_FULL: 409,
    ErrorCode.ROOM_ALREADY_STARTED: 409,
    ErrorCode.NICKNAME_TAKEN: 409,
    ErrorCode.INVALID_NICKNAME: 422,
    ErrorCode.NOT_HOST: 409,
    ErrorCode.NOT_READY: 409,
}


def _room_error_to_http(err: RoomError) -> HTTPException:
    status = _ERROR_STATUS_MAP.get(err.code, 500)
    return HTTPException(
        status_code=status,
        detail={"code": err.code.value, "message": err.args[0]},
    )


def _client_rate_key(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def _enforce_http_rate_limit(request: Request) -> None:
    if _http_rate_limiter.check(_client_rate_key(request)):
        return
    raise HTTPException(
        status_code=429,
        detail={
            "code": ErrorCode.RATE_LIMITED.value,
            "message": "请求过于频繁，请稍后再试",
        },
    )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/rooms")
async def create_room(request: Request, req: NicknameRequest):
    _enforce_http_rate_limit(request)
    mgr = get_room_manager()
    try:
        creds = await mgr.create_room(req.nickname)
    except RoomError as e:
        raise _room_error_to_http(e)
    return {
        "roomCode": creds.room_code,
        "playerId": str(creds.player_id),
        "reconnectToken": creds.reconnect_token,
        "websocketPath": f"/ws/rooms/{creds.room_code}",
    }


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, request: Request, req: NicknameRequest):
    _enforce_http_rate_limit(request)
    mgr = get_room_manager()
    try:
        creds = await mgr.join_room(code, req.nickname)
    except RoomError as e:
        raise _room_error_to_http(e)
    return {
        "roomCode": creds.room_code,
        "playerId": str(creds.player_id),
        "reconnectToken": creds.reconnect_token,
        "websocketPath": f"/ws/rooms/{creds.room_code}",
    }


@app.get("/api/rooms/{code}")
async def get_room(code: str):
    mgr = get_room_manager()
    try:
        room = await mgr.get_room_state(code)
    except RoomError as e:
        raise _room_error_to_http(e)
    from server.models.room import RoomPhase
    return {
        "roomCode": room.code,
        "phase": room.phase.value,
        "playerCount": len(room.players),
        "maxPlayers": RoomManager.MAX_PLAYERS,
        "joinable": (
            room.phase == RoomPhase.LOBBY
            and len(room.players) < RoomManager.MAX_PLAYERS
        ),
    }


# ---------------------------------------------------------------------------
# WebSocket 端点
# ---------------------------------------------------------------------------


@app.websocket("/ws/rooms/{code}")
async def ws_room(websocket: WebSocket, code: str):
    await websocket_endpoint(websocket, code, get_room_manager())


# ---------------------------------------------------------------------------
# 静态文件（必须在 API 路由之后挂载）
# ---------------------------------------------------------------------------

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = _WEB_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


# 挂载 CSS/JS 静态文件
app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")


# ---------------------------------------------------------------------------
# 422 错误格式统一
# ---------------------------------------------------------------------------

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "请求参数校验失败"},
    )
