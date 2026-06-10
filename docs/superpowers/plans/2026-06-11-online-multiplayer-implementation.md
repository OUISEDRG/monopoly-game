# 公网联机大富翁实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单页热座大富翁渐进迁移为可部署到 Render 免费服务的 2–4 人服务端权威公网联机游戏。

**Architecture:** 保留旧单机版作为行为参考，在 `server/` 创建纯 Python 权威规则引擎、房间管理器和 FastAPI WebSocket 服务，在 `web/` 创建只负责网络与渲染的新客户端。每个房间使用单进程内存状态和 `asyncio.Lock` 串行处理，所有有效变化广播版本化完整快照。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、Uvicorn、pytest、FastAPI TestClient、原生 HTML/CSS/JavaScript、Node.js 现有测试、Render Free Web Service。

---

## 执行规则

- 一次只执行一个任务，不跨阶段抢跑。
- 每个任务先写失败测试，再写最小实现。
- 不删除 `monopoly.html`、`monopoly_app.py` 或现有测试。
- 不把服务端规则重新复制到客户端。
- 不引入数据库、Redis、React、Vue 或构建工具。
- 每个任务完成后运行清理归档 Skill 和交接 Skill。
- 每个任务单独提交；如果用户未授权提交，只准备提交范围和信息。

## 目标文件职责

| 路径 | 职责 |
|---|---|
| `server/models/` | 可序列化房间和游戏状态 |
| `server/engine/` | 无网络和 DOM 的权威规则 |
| `server/room_manager.py` | 房间生命周期、锁、连接和广播协调 |
| `server/protocol.py` | Pydantic 消息协议和错误码 |
| `server/transport/websocket.py` | WebSocket 收发和认证适配 |
| `server/scheduler.py` | 回合、交易、拍卖和断线期限 |
| `server/app.py` | FastAPI 入口、HTTP API、静态文件 |
| `web/js/` | 客户端网络、存储、动作和渲染 |
| `tests/engine/` | 纯规则测试 |
| `tests/server/` | 房间和协议测试 |
| `tests/integration/` | 多连接 WebSocket 测试 |

## Task 0: 建立 Python 联机测试环境

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `server/__init__.py`
- Create: `tests/server/test_health.py`

- [ ] **Step 1: 写失败的健康检查导入测试**

```python
from fastapi.testclient import TestClient
from server.app import app


def test_healthz_reports_service_ready():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/server/test_health.py -q
```

Expected: FAIL，原因是 `server.app` 尚不存在。

- [ ] **Step 3: 创建依赖文件**

```text
fastapi
uvicorn[standard]
websockets
pytest
httpx
```

`pytest.ini`：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

- [ ] **Step 4: 创建最小 FastAPI 应用**

Create `server/app.py`：

```python
from fastapi import FastAPI

app = FastAPI(title="Online Monopoly")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/server/test_health.py -q
node --test tests/*.mjs
```

Expected: Python 1 项通过；现有 Node 测试全部通过。

## Task 1: 冻结共享棋盘常量

**Files:**
- Create: `server/engine/board.py`
- Create: `tests/engine/test_board.py`
- Reference: `monopoly.html:1411-1525`

- [ ] **Step 1: 写棋盘基线测试**

测试必须断言：

```python
def test_board_has_forty_spaces():
    assert len(SPACES) == 40


def test_start_and_jail_positions_match_legacy_game():
    assert SPACES[0].type == "go"
    assert SPACES[10].type == "jail"


def test_every_color_group_references_properties():
    for positions in COLOR_GROUPS.values():
        assert positions
        assert all(SPACES[pos].type == "property" for pos in positions)
```

- [ ] **Step 2: 运行并确认失败**

```powershell
python -m pytest tests/engine/test_board.py -q
```

- [ ] **Step 3: 迁移常量**

在 `board.py` 使用冻结 dataclass：

```python
@dataclass(frozen=True, slots=True)
class Space:
    position: int
    name: str
    type: str
    price: int = 0
    base_rent: int = 0
    group: str | None = None
```

逐项迁移 `SPACES`、`COLOR_GROUPS`、`HOUSE_COST`、`RENT_MULTIPLIER`。不得改变数值。

- [ ] **Step 4: 增加旧版对照检查**

编写测试脚本读取 `monopoly.html` 中对应常量，至少比较空间数量、名称、类型、价格和色组。

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/engine/test_board.py -q
node --test tests/*.mjs
```

## Task 2: 建立权威状态模型

**Files:**
- Create: `server/models/player.py`
- Create: `server/models/game.py`
- Create: `server/models/room.py`
- Create: `server/models/__init__.py`
- Create: `tests/engine/test_state_models.py`

- [ ] **Step 1: 写状态序列化测试**

覆盖：

- 玩家默认现金、位置、监狱和破产状态；
- `GameState` 初始阶段为 `WAITING_FOR_ROLL`；
- `RoomState` 只序列化公共字段；
- 重连令牌哈希不出现在公共快照。

- [ ] **Step 2: 定义枚举**

```python
class RoomPhase(str, Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    FINISHED = "finished"


class TurnPhase(str, Enum):
    WAITING_FOR_ROLL = "waiting_for_roll"
    RESOLVING_MOVE = "resolving_move"
    AWAITING_PROPERTY_DECISION = "awaiting_property_decision"
    AWAITING_CARD_DECISION = "awaiting_card_decision"
    AUCTION = "auction"
    TRADE_NEGOTIATION = "trade_negotiation"
    DEBT_RELIEF = "debt_relief"
    TURN_END = "turn_end"
    GAME_OVER = "game_over"
```

- [ ] **Step 3: 定义 dataclass 状态**

使用 `slots=True`，集合和字典使用 `default_factory`，禁止可变默认值共享。

- [ ] **Step 4: 实现公共快照**

提供：

```python
def build_public_snapshot(room: RoomState, server_time_ms: int) -> dict:
    ...
```

快照不包含令牌、哈希、WebSocket 或锁。

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/engine/test_state_models.py -q
```

## Task 3: 建立命令协议、错误码和幂等信封

**Files:**
- Create: `server/protocol.py`
- Create: `tests/server/test_protocol.py`

- [ ] **Step 1: 写消息校验测试**

覆盖合法 `ROLL_DICE`、未知命令、缺失 `requestId`、非法 UUID、负数版本、超过 16 KiB 的消息。

- [ ] **Step 2: 定义协议模型**

```python
class ClientCommand(BaseModel):
    type: Literal["command"]
    request_id: UUID = Field(alias="requestId")
    room_version: int = Field(alias="roomVersion", ge=0)
    command: CommandName
    payload: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 3: 定义错误码枚举和结果构造器**

提供：

```python
def accepted_result(request_id: UUID, room_version: int) -> dict: ...
def rejected_result(request_id: UUID, room_version: int, code: ErrorCode, message: str) -> dict: ...
```

- [ ] **Step 4: 验证**

```powershell
python -m pytest tests/server/test_protocol.py -q
```

## Task 4: 建立大厅房间管理器

**Files:**
- Create: `server/security.py`
- Create: `server/room_manager.py`
- Create: `tests/server/test_room_manager.py`

- [ ] **Step 1: 写大厅失败测试**

覆盖：

- 创建房间得到六位无歧义房间码；
- 2–4 人加入；
- 第五人拒绝；
- 昵称大小写冲突拒绝；
- 非房主不能开始；
- 未全员准备不能开始；
- 全员准备后房主可开始；
- 空大厅销毁。

- [ ] **Step 2: 实现身份工具**

```python
def issue_reconnect_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, digest


def verify_reconnect_token(token: str, expected_digest: str) -> bool:
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return secrets.compare_digest(actual, expected_digest)
```

- [ ] **Step 3: 实现 RoomManager**

关键接口：

```python
async def create_room(self, nickname: str) -> JoinCredentials: ...
async def join_room(self, code: str, nickname: str) -> JoinCredentials: ...
async def set_ready(self, code: str, player_id: UUID, ready: bool) -> RoomState: ...
async def start_game(self, code: str, player_id: UUID) -> RoomState: ...
async def leave_lobby(self, code: str, player_id: UUID) -> None: ...
```

- [ ] **Step 4: 验证**

```powershell
python -m pytest tests/server/test_room_manager.py -q
```

## Task 5: 建立 HTTP 大厅 API 和静态入口

**Files:**
- Modify: `server/app.py`
- Create: `web/index.html`
- Create: `web/styles.css`
- Create: `web/js/app.js`
- Create: `web/js/storage.js`
- Create: `tests/server/test_room_http.py`

- [ ] **Step 1: 写 HTTP 测试**

覆盖 `/`、`/healthz`、创建房间、加入房间、查询不存在房间、查询已开始房间。

- [ ] **Step 2: 添加请求模型**

```python
class NicknameRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=12)
```

- [ ] **Step 3: 注册路由**

返回值必须包含：

```json
{
  "roomCode": "ABC234",
  "playerId": "uuid",
  "reconnectToken": "secret",
  "websocketPath": "/ws/rooms/ABC234"
}
```

- [ ] **Step 4: 创建最小大厅 UI**

页面提供昵称、创建房间、房间码、加入房间和错误区域。身份写入 `localStorage`，不得写入 DOM 日志。

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/server/test_room_http.py -q
```

## Task 6: 建立 WebSocket 认证、连接和大厅广播

**Files:**
- Create: `server/transport/__init__.py`
- Create: `server/transport/websocket.py`
- Modify: `server/room_manager.py`
- Modify: `server/app.py`
- Create: `web/js/network.js`
- Create: `web/js/lobby.js`
- Create: `tests/integration/test_lobby_websocket.py`

- [ ] **Step 1: 写双客户端 WebSocket 测试**

使用 `TestClient.websocket_connect()` 验证：

- 正确令牌连接成功；
- 错误令牌关闭；
- 第二人加入后双方收到相同版本快照；
- 准备状态广播；
- 新连接替换旧连接；
- 断开后 `connected=false`。

- [ ] **Step 2: 实现连接注册**

RoomManager 增加：

```python
async def connect(self, code: str, player_id: UUID, token: str, socket: WebSocket) -> None: ...
async def disconnect(self, code: str, player_id: UUID, socket: WebSocket) -> None: ...
async def broadcast_snapshot(self, room: RoomState) -> None: ...
```

- [ ] **Step 3: 实现消息循环**

仅接收 JSON 文本；超过大小限制、协议错误或认证失败时使用明确关闭码。

- [ ] **Step 4: 客户端自动重连**

退避序列使用 1、2、4、8、15 秒；成功后重置。页面显示“正在重连”，但不清除身份。

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/integration/test_lobby_websocket.py -q
```

## Task 7: 建立基础权威回合引擎

**Files:**
- Create: `server/engine/commands.py`
- Create: `server/engine/rules.py`
- Create: `server/engine/state_machine.py`
- Create: `tests/engine/test_turn_engine.py`

- [ ] **Step 1: 写基础回合测试**

覆盖：

- 非当前玩家不能掷骰；
- 客户端不能指定点数；
- 固定随机源得到确定结果；
- 经过起点加钱；
- 双数额外回合；
- 三次双数进监狱；
- 普通落点推进到下一玩家；
- 每个有效命令版本加一。

- [ ] **Step 2: 定义随机源**

```python
class RandomSource(Protocol):
    def roll_die(self) -> int: ...


class SystemRandomSource:
    def __init__(self) -> None:
        self._random = random.SystemRandom()

    def roll_die(self) -> int:
        return self._random.randint(1, 6)
```

- [ ] **Step 3: 定义命令结果**

```python
@dataclass(slots=True)
class EngineResult:
    changed: bool
    events: list[dict]
    private_events: dict[UUID, list[dict]]
```

- [ ] **Step 4: 实现 `apply_command`**

接口：

```python
def apply_command(
    game: GameState,
    actor_id: UUID,
    command: CommandName,
    payload: dict,
    random_source: RandomSource,
    now: datetime,
) -> EngineResult:
    ...
```

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/engine/test_turn_engine.py -q
```

## Task 8: 迁移地产、租金、税费和卡牌

**Files:**
- Modify: `server/engine/rules.py`
- Create: `server/engine/cards.py`
- Create: `tests/engine/test_landing_rules.py`
- Create: `tests/engine/test_cards.py`

- [ ] **Step 1: 写规则对照测试**

为每种空间至少覆盖一个场景：

- 无主地产进入购买决定；
- 购买扣款并登记所有权；
- 放弃进入拍卖；
- 支付普通租金；
- 完整色组和建筑租金；
- 抵押地产不收租；
- 税费进入免费停车池；
- 起点、免费停车、进监狱；
- 机会和命运卡。

- [ ] **Step 2: 将卡牌动作改为数据 + 命令**

禁止保存 Python lambda 到状态。卡牌定义使用稳定 ID，规则函数按 ID 执行。

- [ ] **Step 3: 处理待决策**

需要玩家选择的卡牌设置 `pending_decision`，不在同一调用中猜测客户端选择。

- [ ] **Step 4: 验证**

```powershell
python -m pytest tests/engine/test_landing_rules.py tests/engine/test_cards.py -q
```

## Task 9: 迁移建造、出售建筑和抵押

**Files:**
- Modify: `server/engine/rules.py`
- Create: `tests/engine/test_property_management.py`

- [ ] **Step 1: 写失败测试**

覆盖完整色组、抵押阻止建造、平均建设、平均出售、资金不足、解押费用和非法所有者。

- [ ] **Step 2: 实现命令**

增加：

- `BUILD`
- `SELL_BUILDING`
- `MORTGAGE`
- `UNMORTGAGE`

每条命令只接收地产位置，不接收最终金额。

- [ ] **Step 3: 验证**

```powershell
python -m pytest tests/engine/test_property_management.py -q
```

## Task 10: 迁移多人拍卖

**Files:**
- Create: `server/engine/auction.py`
- Modify: `server/engine/state_machine.py`
- Create: `tests/engine/test_auction_engine.py`

- [ ] **Step 1: 写失败测试**

覆盖起拍价、最低加价、超现金拒绝、主动退出、轮转、无人出价、最终成交和断线超时退出。

- [ ] **Step 2: 定义 AuctionState**

必须保存地产、最高价、最高出价者、当前响应者、活跃竞拍者、截止时间和完成后的恢复动作。

- [ ] **Step 3: 实现 `PLACE_BID` 与 `PASS_AUCTION`**

所有修改在单次引擎调用中完成，成交时原子扣款和转移地产。

- [ ] **Step 4: 验证**

```powershell
python -m pytest tests/engine/test_auction_engine.py -q
```

## Task 11: 迁移完整玩家交易

**Files:**
- Create: `server/engine/trade.py`
- Modify: `server/engine/state_machine.py`
- Create: `tests/engine/test_trade_engine.py`
- Create: `tests/integration/test_trade_privacy.py`

- [ ] **Step 1: 写交易规则测试**

覆盖地产、现金、出狱卡、建筑限制、重复资产、现金不足、两轮还价、过期资产和原子交割。

- [ ] **Step 2: 写隐私测试**

三客户端连接时：

- 发起者和接收者收到完整报价；
- 第三人只收到公共交易元数据；
- 日志不包含完整报价。

- [ ] **Step 3: 实现 TradeState**

保存发起者、接收者、报价、请求、还价次数、当前响应者、截止时间和原回合剩余时间。

- [ ] **Step 4: 实现命令**

- `PROPOSE_TRADE`
- `ACCEPT_TRADE`
- `REJECT_TRADE`
- `COUNTER_TRADE`

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/engine/test_trade_engine.py tests/integration/test_trade_privacy.py -q
```

## Task 12: 迁移债务、破产和游戏结束

**Files:**
- Create: `server/engine/debt.py`
- Modify: `server/engine/state_machine.py`
- Create: `tests/engine/test_debt_and_bankruptcy.py`

- [ ] **Step 1: 写失败测试**

覆盖：

- 真人自主债务操作；
- 无合法操作破产；
- 有债权人资产转移；
- 无债权人逐块拍卖；
- 破产玩家退出回合和交易；
- 仅剩一人结束；
- 自动债务策略多轮卖房。

- [ ] **Step 2: 实现 DebtState**

保存负债玩家、债权人、恢复阶段、合法动作和截止时间。

- [ ] **Step 3: 实现 `DEBT_ACTION`**

只允许出售一栋建筑或抵押一处地产。每次操作后重新计算债务。

- [ ] **Step 4: 实现确定性自动处置**

顺序固定为：

1. 按可出售建筑收益从低到高出售，持续重新扫描平均出售约束；
2. 按抵押价值从低到高抵押；
3. 仍负债则破产。

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/engine/test_debt_and_bankruptcy.py -q
```

## Task 13: 接入引擎命令、版本和幂等

**Files:**
- Modify: `server/room_manager.py`
- Modify: `server/transport/websocket.py`
- Create: `tests/integration/test_command_pipeline.py`

- [ ] **Step 1: 写并发管线测试**

覆盖：

- 两客户端同时掷骰仅一个成功；
- 重复 `requestId` 不重复执行；
- 旧版本返回 `STALE_STATE`；
- 有效命令广播相同新版本；
- 引擎异常不增加版本。

- [ ] **Step 2: 实现锁内处理**

```python
async with runtime.lock:
    validate_version()
    check_idempotency()
    result = apply_command(...)
    if result.changed:
        room.version += 1
    store_request_result()
```

- [ ] **Step 3: 广播公共与私密消息**

先向命令发送者返回结果，再广播快照；私密事件只发目标玩家。

- [ ] **Step 4: 验证**

```powershell
python -m pytest tests/integration/test_command_pipeline.py -q
```

## Task 14: 实现计时器和断线重连

**Files:**
- Create: `server/scheduler.py`
- Create: `server/engine/timeout_policy.py`
- Modify: `server/room_manager.py`
- Create: `tests/server/test_scheduler.py`
- Create: `tests/integration/test_reconnect.py`

- [ ] **Step 1: 使用可注入时钟写失败测试**

测试配置将 90 秒、45 秒、30 秒和 5 分钟缩短为毫秒级，禁止测试真实等待。

- [ ] **Step 2: 实现 DeadlineConfig**

```python
@dataclass(frozen=True, slots=True)
class DeadlineConfig:
    turn_seconds: int = 90
    trade_seconds: int = 45
    auction_seconds: int = 30
    disconnect_seconds: int = 300
```

- [ ] **Step 3: 实现超时策略**

覆盖自动掷骰、放弃购买、拍卖退出、交易拒绝、债务自动处置和断线破产。

- [ ] **Step 4: 实现重连**

正确令牌恢复原玩家并收到完整快照；错误令牌拒绝；新连接替换旧连接。

- [ ] **Step 5: 验证**

```powershell
python -m pytest tests/server/test_scheduler.py tests/integration/test_reconnect.py -q
```

## Task 15: 完成联机客户端棋盘和操作层

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`
- Create: `web/js/game-renderer.js`
- Create: `web/js/actions.js`
- Create: `web/js/modals.js`
- Modify: `web/js/app.js`
- Create: `tests/browser/online_smoke.spec.mjs`

- [ ] **Step 1: 建立渲染夹具**

保存一份固定 `state_snapshot`，测试棋盘、玩家面板、当前回合、按钮禁用和截止时间显示。

- [ ] **Step 2: 迁移现有视觉结构**

从 `monopoly.html` 迁移必要 HTML/CSS，但删除：

- 本地权威状态变量；
- `Math.random()` 骰子；
- 本地资金和地产修改；
- AI 逻辑；
- 热座交接遮罩。

- [ ] **Step 3: 实现动作映射**

每个按钮只调用：

```javascript
network.sendCommand(commandName, payload)
```

按钮是否启用完全由快照中的阶段和当前操作者决定。

- [ ] **Step 4: 实现动画**

动画完成不得推进规则，只在收到快照后表现移动、骰子和资金变化。

- [ ] **Step 5: 浏览器验证**

使用两个独立浏览器上下文完成创建、加入、准备、开始和一次掷骰。

## Task 16: 安全、限流和日志

**Files:**
- Create: `server/logging_config.py`
- Modify: `server/app.py`
- Modify: `server/transport/websocket.py`
- Create: `tests/server/test_security.py`

- [ ] **Step 1: 写失败测试**

覆盖昵称清理、未知 Origin、超大消息、命令洪泛、令牌不出现在日志和错误响应。

- [ ] **Step 2: 实现生产配置**

环境变量：

```text
APP_ENV
ALLOWED_ORIGINS
TURN_TIMEOUT_SECONDS
TRADE_TIMEOUT_SECONDS
AUCTION_TIMEOUT_SECONDS
DISCONNECT_TIMEOUT_SECONDS
LOG_LEVEL
```

- [ ] **Step 3: 添加结构化日志**

只记录脱敏房间、短玩家 ID、请求 ID、版本、命令和错误码。

- [ ] **Step 4: 验证**

```powershell
python -m pytest tests/server/test_security.py -q
```

## Task 17: Render 免费部署配置

**Files:**
- Create: `render.yaml`
- Modify: `README.md`
- Create: `docs/superpowers/workflow/render-free-deployment.md`
- Create: `tests/server/test_deployment_config.py`

- [ ] **Step 1: 写部署配置测试**

断言启动命令只有一个 worker，绑定 `0.0.0.0` 和 `$PORT`，健康检查为 `/healthz`。

- [ ] **Step 2: 创建 `render.yaml`**

```yaml
services:
  - type: web
    name: online-monopoly
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn server.app:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /healthz
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.11
      - key: APP_ENV
        value: production
```

- [ ] **Step 3: 编写部署步骤**

必须包含 GitHub 推送、Render Blueprint、环境变量、首次冷启动、免费休眠和重启丢房间说明。

- [ ] **Step 4: 本地生产命令验证**

```powershell
$env:PORT=8000
uvicorn server.app:app --host 0.0.0.0 --port $env:PORT
```

访问 `/healthz`、`/` 并连接 WebSocket。

## Task 18: 完整验收与上线门槛

**Files:**
- Create: `tests/integration/test_full_game.py`
- Create: `docs/superpowers/changelogs/2026-06-11-online-multiplayer-changelog.md`
- Modify: `README.md`

- [ ] **Step 1: 创建确定性完整对局测试**

使用固定随机源和缩短超时，覆盖创建到最后一人胜利，不依赖真实等待。

- [ ] **Step 2: 运行完整测试矩阵**

```powershell
python -m pytest -q
node --test tests/*.mjs
$pythonFiles = @('monopoly_app.py') + (
  Get-ChildItem -LiteralPath 'server' -Recurse -Filter '*.py' |
  ForEach-Object FullName
)
python -m py_compile $pythonFiles
git diff --check
```

- [ ] **Step 3: 浏览器验收**

必须验证：

1. 两台设备不同网络加入同房间；
2. 全员准备和房主开始；
3. 购买、拍卖、建造、抵押；
4. 完整交易和两轮还价；
5. 刷新后重连；
6. 缩短配置下断线清算；
7. 桌面和 390×844；
8. 完整结束一局。

- [ ] **Step 4: Render 验收**

记录公开 URL、部署 commit、冷启动时间、浏览器控制台错误、服务器日志和已知限制。

- [ ] **Step 5: 保留旧版**

首个公网版本发布后仍保留旧单机入口至少一个发布周期。只有用户另行批准，才能删除旧实现。

## 任务顺序与里程碑

| 里程碑 | 任务 | 可观察成果 |
|---|---|---|
| M1 基础 | 0–3 | Python 测试环境、棋盘常量、状态和协议 |
| M2 大厅 | 4–6 | 可创建、加入、准备、开始并实时广播 |
| M3 核心玩法 | 7–9 | 服务端可完成基础回合和地产管理 |
| M4 复杂玩法 | 10–12 | 拍卖、交易、债务和破产完整 |
| M5 可靠性 | 13–14 | 幂等、版本、计时、断线重连 |
| M6 客户端 | 15–16 | 可操作联机棋盘和安全边界 |
| M7 上线 | 17–18 | Render 部署和完整公网验收 |

## 建议提交划分

只有用户明确授权后才执行提交；否则将对应文件列入交接报告。

| 任务 | 建议提交信息 |
|---|---|
| 0 | `build: add FastAPI test foundation` |
| 1 | `feat: add authoritative board constants` |
| 2 | `feat: add multiplayer state models` |
| 3 | `feat: define websocket command protocol` |
| 4 | `feat: add lobby room manager` |
| 5 | `feat: add room HTTP API and lobby shell` |
| 6 | `feat: add authenticated lobby websocket` |
| 7 | `feat: add authoritative turn engine` |
| 8 | `feat: migrate landing and card rules` |
| 9 | `feat: migrate property management rules` |
| 10 | `feat: add multiplayer auction engine` |
| 11 | `feat: add private player trade flow` |
| 12 | `feat: add debt and bankruptcy engine` |
| 13 | `feat: add versioned idempotent command pipeline` |
| 14 | `feat: add deadlines and reconnect handling` |
| 15 | `feat: add online game client` |
| 16 | `security: harden multiplayer transport` |
| 17 | `deploy: add Render free service configuration` |
| 18 | `test: complete multiplayer release acceptance` |

## 执行者首轮提示词

```text
你是执行 AI。本轮只执行《公网联机大富翁实施计划》的 Task 0，不得开始 Task 1。

开始前阅读：
1. `.agents/skills/ai-handoff-coordinator/SKILL.md`
2. `.agents/skills/cleanup-archive-coordinator/SKILL.md`
3. `docs/superpowers/specs/2026-06-11-online-multiplayer-design.md`
4. `docs/superpowers/plans/2026-06-11-online-multiplayer-implementation.md`

目标：
建立 Python 联机服务的最小测试环境和 `/healthz` FastAPI 入口，同时保证现有单机测试不回归。

允许修改：
- `requirements.txt`
- `pytest.ini`
- `server/__init__.py`
- `server/app.py`
- `tests/server/test_health.py`
- 本轮清理归档记录
- 最新交接报告

要求：
- 严格按 Task 0 测试先行。
- 不修改 `monopoly.html`、`monopoly_app.py` 和现有 Node 测试。
- 不实现房间、WebSocket 或游戏规则。
- 不覆盖任何前序未提交改动。

必跑检查：
- `python -m pytest tests/server/test_health.py -q`
- `node --test tests/*.mjs`
- `python -m py_compile server/app.py monopoly_app.py`
- `git diff --check`

完成后：
- 运行清理归档 Skill。
- 生成清理归档记录。
- 新建并核验交接报告。
- 删除旧交接报告，只保留最新报告。
- 下一任务只能发布 Task 1。
```
