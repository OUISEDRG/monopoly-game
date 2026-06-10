# 公网联机大富翁设计规范

## 1. 目标

把当前单页、单进程、热座式大富翁升级为可免费部署到 Render 的公网房间制游戏。

第一版面向朋友间游玩，不追求商业化基础设施，但必须具备可信同步、断线重连、超时托管和完整规则一致性。

## 2. 已确认产品决策

- 部署平台：Render 免费 Web Service。
- 服务端：Python、FastAPI、Uvicorn、WebSocket。
- 玩家数量：2–4 名纯真人。
- 加入方式：昵称 + 六位房间码。
- 身份：无需注册，使用服务器签发的重连令牌。
- 开局：所有玩家准备后，由房主手动开始。
- 回合时限：90 秒。
- 交易：保留地产、现金、出狱卡及最多两轮还价。
- 交易计时：普通回合计时暂停，交易回应限时 45 秒。
- 断线：席位保留 5 分钟，可凭令牌重连。
- 断线超时：按无债权破产处理，地产逐块拍卖。
- 持久化：第一版不保存跨服务器重启的房间。
- 房间销毁：最后一个连接离开后销毁。
- 第一版不包含：AI、账号、聊天、观战、排行榜、匹配系统、跨重启存档。

## 3. 成功标准

1. 两至四名玩家可从不同设备通过房间码完成一整局。
2. 任一客户端都不能自行决定骰子、现金、所有权或回合顺序。
3. 所有客户端在相同 `roomVersion` 下得到一致公共状态。
4. 刷新或短暂断网后，玩家可在五分钟内恢复原席位。
5. 无响应玩家不会永久卡住游戏。
6. 拍卖、交易、债务、破产和最后一人胜利均由服务端正确裁决。
7. Render 免费实例被重启后，旧房间失效但服务能正常重新创建房间。

## 4. 非目标

- 不将第一版设计成大型 MMO。
- 不支持同一房间跨多个服务实例运行。
- 不使用 Redis、PostgreSQL 或外部消息队列。
- 不在客户端复刻一套权威规则。
- 不保证服务器重启后的对局恢复。
- 不在本次迁移中修改既有经济规则。

## 5. 架构原则

### 5.1 服务端权威

客户端只提交命令意图。服务端负责：

- 验证身份与连接；
- 验证房间阶段和回合权限；
- 生成随机结果；
- 执行规则；
- 修改状态；
- 递增版本；
- 广播快照或私密消息。

客户端不得提交最终金额、骰子点数、地产所有权或下一玩家 ID。

### 5.2 单房间串行执行

每个房间有一个 `asyncio.Lock`。所有会改变状态的命令、计时器和断线清算均在锁内串行执行，避免双击、同时出价或计时器与玩家命令竞争。

### 5.3 显式状态机

服务端禁止依靠 DOM、动画回调或散落的 `setTimeout` 推进规则。每个游戏阶段必须显式记录，并限定合法命令。

### 5.4 完整快照优先

第一版状态很小。每次有效变化后广播完整公共快照，减少增量事件遗漏和重连复杂度。私密交易内容使用单独消息发送。

### 5.5 渐进迁移

保留现有 `monopoly.html` 和测试作为行为参考。新联机版进入独立目录，阶段完成前不删除旧入口。

## 6. 目标目录

```text
server/
├── __init__.py
├── app.py
├── config.py
├── protocol.py
├── security.py
├── room_manager.py
├── scheduler.py
├── models/
│   ├── __init__.py
│   ├── player.py
│   ├── room.py
│   └── game.py
├── engine/
│   ├── __init__.py
│   ├── board.py
│   ├── commands.py
│   ├── rules.py
│   ├── state_machine.py
│   ├── auction.py
│   ├── trade.py
│   ├── debt.py
│   └── timeout_policy.py
└── transport/
    ├── __init__.py
    └── websocket.py

web/
├── index.html
├── styles.css
└── js/
    ├── app.js
    ├── network.js
    ├── storage.js
    ├── lobby.js
    ├── game-renderer.js
    ├── actions.js
    └── modals.js

tests/
├── engine/
├── server/
├── integration/
└── browser/

requirements.txt
render.yaml
```

## 7. 服务边界

### `server/app.py`

- 创建 FastAPI 应用。
- 托管 `web/` 静态文件。
- 提供 `/healthz`。
- 注册房间 HTTP 路由和 WebSocket 路由。
- 应用启动与关闭时启动/停止调度器。

### `server/protocol.py`

- 定义客户端命令、服务端响应和错误码。
- 使用 Pydantic 校验消息结构。
- 不包含游戏规则。

### `server/room_manager.py`

- 创建、查找、销毁房间。
- 控制房间码唯一性。
- 协调连接、重连和广播。
- 持有进程内房间字典。

### `server/models/`

- 只定义可序列化状态。
- 不访问 WebSocket、DOM 或全局管理器。
- 所有时间统一存储为 UTC 时间戳或单调时钟截止值。

### `server/engine/`

- 接收状态、命令和可注入随机源。
- 返回新状态及领域事件。
- 不直接发送网络消息。
- 不读取系统环境变量。

### `server/scheduler.py`

- 检查回合、交易、拍卖和断线期限。
- 到期时在房间锁内调用超时策略。
- 不自行拼接游戏状态。

### `web/js/network.js`

- 管理 WebSocket、重连、心跳、请求 ID 和消息分发。
- 不修改游戏规则状态。

### `web/js/game-renderer.js`

- 将服务端快照渲染为现有棋盘 UI。
- 不执行资金、地产或回合计算。

## 8. 房间模型

```text
RoomState
- code: str
- phase: lobby | playing | finished
- host_player_id: UUID
- players: list[PlayerState]
- game: GameState | null
- version: int
- created_at: datetime
- last_nonempty_at: datetime

RoomRuntime
- lock: asyncio.Lock
- sockets_by_player_id
- processed_request_ids
- disconnect_deadlines
- timer_task metadata
```

`RoomRuntime` 不进入公共快照。

## 9. 玩家模型

```text
PlayerState
- id: UUID
- nickname: str
- seat: int
- color: str
- ready: bool
- connected: bool
- disconnected_at: datetime | null
- bankrupt: bool
- money: int
- position: int
- properties: list[int]
- in_jail: bool
- jail_turns: int
- has_get_out_of_jail_card: bool
- consecutive_doubles: int
```

重连令牌哈希存于服务器私密身份记录，不进入 `PlayerState` 或公共快照。

## 10. 游戏模型

```text
GameState
- phase: TurnPhase
- current_player_id: UUID
- turn_number: int
- turn_deadline: datetime | null
- trade_window_available: bool
- free_parking_money: int
- last_dice: tuple[int, int] | null
- property_owners: dict[int, UUID]
- mortgage_status: dict[int, bool]
- building_levels: dict[int, int]
- auction: AuctionState | null
- trade: TradeState | null
- debt: DebtState | null
- pending_decision: PendingDecision | null
- logs: bounded list[GameLog]
- winner_player_id: UUID | null
```

## 11. 回合状态机

```text
LOBBY
WAITING_FOR_ROLL
RESOLVING_MOVE
AWAITING_PROPERTY_DECISION
AWAITING_CARD_DECISION
AUCTION
TRADE_NEGOTIATION
DEBT_RELIEF
TURN_END
GAME_OVER
```

### 合法命令矩阵

| 阶段 | 合法命令 |
|---|---|
| `LOBBY` | `SET_READY`, `START_GAME`, `LEAVE_ROOM` |
| `WAITING_FOR_ROLL` | `ROLL_DICE`, `PROPOSE_TRADE`, `BUILD`, `SELL_BUILDING`, `MORTGAGE`, `UNMORTGAGE` |
| `AWAITING_PROPERTY_DECISION` | `BUY_PROPERTY`, `DECLINE_PROPERTY` |
| `AWAITING_CARD_DECISION` | 对应卡牌选择命令 |
| `AUCTION` | `PLACE_BID`, `PASS_AUCTION` |
| `TRADE_NEGOTIATION` | `ACCEPT_TRADE`, `REJECT_TRADE`, `COUNTER_TRADE` |
| `DEBT_RELIEF` | `DEBT_ACTION` |
| `TURN_END` | 无客户端命令 |
| `GAME_OVER` | `LEAVE_ROOM` |

服务端还必须验证命令发送者是否为当前操作者。

## 12. 房间生命周期

### 创建

1. `POST /api/rooms` 接收昵称。
2. 服务器创建房间和房主。
3. 返回房间码、玩家 ID、重连令牌和 WebSocket URL。

### 加入

1. `POST /api/rooms/{code}/join` 接收昵称。
2. 仅 `lobby` 阶段可加入。
3. 房间最多四人。
4. 同一房间昵称大小写折叠后必须唯一。

### 准备与开始

- 玩家通过 WebSocket 发送 `SET_READY`。
- 房主本人也必须准备。
- 只有房主可发送 `START_GAME`。
- 人数必须为 2–4，且所有玩家已准备。
- 开始后锁定座位和加入入口。

### 销毁

- 大厅中所有玩家离开后立即销毁。
- 游戏中所有玩家都断开时可立即销毁，因为第一版不保存对局。
- 游戏结束且所有连接离开后销毁。

## 13. 身份与重连

### 令牌

- 使用 `secrets.token_urlsafe(32)` 生成。
- 返回明文一次。
- 服务端只保存 SHA-256 哈希。
- 浏览器保存在 `localStorage`。
- 日志不得输出令牌。

### 重连

WebSocket 连接携带：

```text
/ws/rooms/{code}?playerId={uuid}&token={secret}
```

验证成功后：

1. 替换同一玩家的旧连接。
2. 标记 `connected=true`。
3. 清除断线期限。
4. 发送完整公共快照和属于该玩家的私密状态。

验证失败返回策略违规关闭码，不泄露具体令牌信息。

## 14. WebSocket 协议

### 客户端信封

```json
{
  "type": "command",
  "requestId": "uuid",
  "roomVersion": 42,
  "command": "ROLL_DICE",
  "payload": {}
}
```

### 成功响应

```json
{
  "type": "command_result",
  "requestId": "uuid",
  "accepted": true,
  "roomVersion": 43
}
```

### 失败响应

```json
{
  "type": "command_result",
  "requestId": "uuid",
  "accepted": false,
  "roomVersion": 43,
  "error": {
    "code": "NOT_CURRENT_PLAYER",
    "message": "当前不是你的回合"
  }
}
```

### 快照

```json
{
  "type": "state_snapshot",
  "roomVersion": 43,
  "serverTime": 1781123456789,
  "state": {}
}
```

### 私密消息

交易完整报价只发送给交易双方。公共快照仅包含：

- 交易是否存在；
- 发起者和接收者；
- 当前回应者；
- 还价轮数；
- 截止时间。

## 15. 版本与幂等

- 每次有效状态变更后 `version += 1`。
- 命令携带旧版本时返回 `STALE_STATE` 和最新快照。
- 每名玩家保存最近至少 200 个 `requestId`。
- 重复 `requestId` 返回原处理结果，不重复执行。
- 纯连接状态变化也递增版本，以便所有客户端刷新在线状态。

## 16. 随机性

- 骰子和卡牌由服务端生成。
- 引擎接受 `RandomSource` 接口，测试使用固定序列。
- 客户端不得上传点数或卡牌索引。
- 日志记录骰子结果，但不泄露随机内部状态。

## 17. 超时策略

### 普通回合 90 秒

- `WAITING_FOR_ROLL`：关闭交易窗口并自动掷骰。
- `AWAITING_PROPERTY_DECISION`：默认放弃购买并开始拍卖。
- `AWAITING_CARD_DECISION`：选择预定义的最低风险合法选项。
- 监狱决策：优先使用出狱卡，其次现金足够时支付，否则结束监狱回合。
- `DEBT_RELIEF`：执行确定性的自动处置策略，直到偿债或破产。

### 交易回应 45 秒

- 到期自动拒绝交易。
- 恢复原回合计时，剩余时间不得少于 15 秒。

### 拍卖回应 30 秒

- 当前竞拍者到期自动退出拍卖。

### 断线 5 分钟

- 当前回合计时继续。
- 断线玩家需要决策时仍按超时策略处理。
- 五分钟到期后无债权破产并逐块拍卖。

## 18. 交易规则

- 仅当前玩家在掷骰前可发起。
- 每回合最多一笔交易。
- 交易双方必须仍在游戏中。
- 可包含多个地产、非负现金和一张出狱卡。
- 建筑相关限制沿用当前规则。
- 最多两轮还价。
- 最终接受前重新校验资产和现金。
- 交割在房间锁内原子执行。
- 任一方破产或五分钟断线到期时取消。
- 非交易双方看不到资产明细。

## 19. 拍卖规则

- 拍卖顺序按座位循环。
- 最低加价 50。
- 出价不得超过当前现金。
- 主动退出后不能重新加入该次拍卖。
- 无人出价时地产保持无主。
- 断线玩家由拍卖超时策略自动退出。
- 破产清算地产逐块创建新的拍卖状态。

## 20. 债务与破产

- 债务动作必须由服务端验证。
- 真人可在期限内自主出售建筑和抵押。
- 债务超时使用确定性保守策略。
- 有债权人时按现有规则转移资产。
- 无债权人或断线超时时，地产逐块拍卖。
- 破产玩家退出后续回合和交易。
- 仅剩一名未破产玩家时结束游戏。

## 21. 客户端职责

- 渲染服务器快照。
- 只在服务端快照允许时启用按钮。
- 对命令显示等待状态，避免重复点击。
- 收到 `STALE_STATE` 后直接采用最新快照。
- 断线后显示重连倒计时和自动重连状态。
- 不进行权威规则计算。
- 动画只表现已经发生的服务端结果。

## 22. HTTP API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/healthz` | Render 健康检查 |
| `GET` | `/` | 联机版入口 |
| `POST` | `/api/rooms` | 创建房间 |
| `POST` | `/api/rooms/{code}/join` | 加入房间 |
| `GET` | `/api/rooms/{code}` | 返回房间是否存在及可加入状态，不返回私密信息 |
| `WS` | `/ws/rooms/{code}` | 游戏实时连接 |

## 23. 错误码

至少定义：

- `INVALID_MESSAGE`
- `INVALID_NICKNAME`
- `ROOM_NOT_FOUND`
- `ROOM_FULL`
- `ROOM_ALREADY_STARTED`
- `NICKNAME_TAKEN`
- `AUTH_FAILED`
- `NOT_HOST`
- `NOT_READY`
- `NOT_CURRENT_PLAYER`
- `INVALID_PHASE`
- `INVALID_COMMAND`
- `STALE_STATE`
- `DUPLICATE_REQUEST`
- `INSUFFICIENT_FUNDS`
- `ASSET_CHANGED`
- `RATE_LIMITED`

## 24. 安全与滥用限制

- 昵称清理控制字符，长度 1–12。
- 单条 WebSocket 文本消息上限 16 KiB。
- 单连接命令频率建议不超过每秒 10 条，突发 20 条。
- HTTP 创建/加入接口按 IP 做轻量限流。
- 校验 `Origin`，生产环境只允许 Render 域名和配置域名。
- 房间码不作为认证信息。
- 错误消息不得返回堆栈或令牌。
- 所有 HTML 文本使用 `textContent` 或转义。

## 25. Render 免费部署约束

- 进程只启动一个 Uvicorn worker，否则内存房间不会共享。
- 启动命令：

```text
uvicorn server.app:app --host 0.0.0.0 --port $PORT
```

- 免费服务空闲 15 分钟后可能休眠。
- 活跃 WebSocket 消息可保持服务运行。
- 本地文件系统和内存状态在重启后丢失。
- `/healthz` 不依赖房间状态。
- 服务启动后旧房间自然失效，客户端应提示重新建房。

## 26. 可观测性

结构化日志包含：

- 事件名；
- 房间码的哈希或脱敏值；
- 玩家 ID 的短标识；
- `requestId`；
- `roomVersion`；
- 命令结果和错误码；
- 连接、断线、重连、房间销毁。

不得记录：

- 重连令牌；
- 完整私密交易报价；
- 浏览器本地存储内容。

## 27. 测试策略

### 引擎单元测试

- 命令合法阶段；
- 非当前玩家拒绝；
- 固定随机源；
- 资金和地产守恒；
- 双数、监狱、卡牌；
- 建造和抵押；
- 拍卖；
- 交易；
- 债务和破产；
- 超时策略。

### 房间服务测试

- 创建、加入、准备、开始；
- 房主权限；
- 房间容量和昵称冲突；
- 房间销毁；
- 重连令牌；
- 旧连接替换；
- 断线期限。

### WebSocket 集成测试

- 两至四个 TestClient 连接；
- 状态广播一致；
- 重复命令幂等；
- 旧版本拒绝；
- 私密交易不可见；
- 断线重连恢复；
- 超时命令和玩家命令竞争。

### 浏览器端测试

- 创建和加入房间；
- 准备和开始；
- 刷新恢复；
- 桌面和 390×844；
- 禁用非法按钮；
- 网络中断提示；
- 完整一局冒烟测试。

## 28. 迁移策略

1. 先为当前规则建立行为清单和夹具。
2. 创建 Python 纯状态模型和基础引擎。
3. 逐模块迁移规则，每迁移一个模块就做新旧行为对照。
4. 创建大厅和 WebSocket，不立即迁移全部玩法。
5. 基础回合稳定后再迁移拍卖、交易、债务。
6. 联机客户端只消费服务端快照。
7. 完整验收前保留旧单机入口。

## 29. 发布门槛

只有满足以下条件才可把联机入口标记为正式：

- 全量 Python 与现有 Node 测试通过；
- 两客户端完整对局通过；
- 四客户端大厅和回合同步通过；
- 刷新重连通过；
- 断线五分钟可使用缩短时钟的测试配置验证；
- Render 免费环境部署成功；
- 浏览器控制台无未处理错误；
- 移动端无横向溢出；
- 安全检查确认客户端无法指定骰子和资产结果。

## 30. 参考资料

- FastAPI WebSocket：https://fastapi.tiangolo.com/advanced/websockets/
- FastAPI WebSocket 测试：https://fastapi.tiangolo.com/advanced/testing-websockets/
- Render FastAPI 部署：https://render.com/docs/deploy-fastapi
- Render WebSocket：https://render.com/docs/websocket
- Render 免费服务限制：https://render.com/docs/free

