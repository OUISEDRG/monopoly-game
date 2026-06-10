# 真人玩家债务处置中心 - 更新记录

> **日期**: 2026-06-10
> **版本**: v2.x (大富翁 Monopoly)
> **功能**: 真人玩家负债时自主选择处置资产，替代系统自动处置

---

## 变更概述

此前，真人玩家现金变为负数时，系统会自动按一定规则选择出售哪些建筑或抵押哪些地产。现在改为：游戏暂停当前流程，由玩家在专用面板中自主选择处置哪些合法资产。

AI 玩家保持原有的自动处置行为不变。

---

## 核心变更

### 1. 债务处置状态机

新增全局状态 `debtReliefState`，记录债务处置期间的完整上下文：

```
debtReliefState = {
  playerId,       // 负债玩家 ID
  creditorId,     // 债权人 ID（可为空）
  initialDebt,    // 初始负债金额
  resume,         // 恢复回调（债务处理结束后执行的动作）
  completed,      // 是否已完成（防止重复执行）
}
```

关键函数：

| 函数 | 文件位置 | 职责 |
|------|---------|------|
| `startHumanDebtRelief()` | monopoly.html:L3764 | 启动债务处置面板，记录状态和回调 |
| `finishDebtRelief()` | monopoly.html:L3778 | 完成处置，关闭面板，执行恢复回调（最多一次） |
| `autoResolveAIDebt()` | monopoly.html:L3788 | AI 自动出售建筑→抵押地产 |
| `finalizePlayerBankruptcy()` | monopoly.html:L3728 | 破产清算（债权人转移/公开拍卖） |
| `checkBankruptcy()` | monopoly.html:L3801 | 入口分流：真人→手动处置 / AI→自动处置 / 无操作→破产 |

### 2. 债务处置资格模型

| 函数 | 文件位置 | 职责 |
|------|---------|------|
| `getDebtReliefActions()` | monopoly.html:L2730 | 扫描玩家全部地产，返回可出售建筑列表和可抵押地产列表 |
| `hasDebtReliefActions()` | monopoly.html:L2755 | 判断是否还有合法处置操作 |
| `getDebtReliefBlockReason()` | monopoly.html:L2760 | 返回某地产不可操作的明确原因 |

合法性规则：
- **出售建筑**：遵守平均出售规则（只能从等级最高的地产开始卖）
- **抵押地产**：地产未抵押、无建筑、同色组内无任何建筑

### 3. 债务处置弹窗 UI

| 元素 ID | 位置 | 说明 |
|---------|------|------|
| `debtReliefModal` | L1233 | 弹窗容器 |
| `debtReliefTitle` | L1236 | 玩家名称 + "债务处置" |
| `debtReliefCash` | L1238 | 当前现金（红色高亮） |
| `debtReliefNeeded` | L1239 | 仍需筹集金额 |
| `debtReliefProgress` | L1241 | 偿债进度条（金色填充动画） |
| `debtReliefAssets` | L1244 | 可滚动资产清单 |
| `debtReliefStatus` | L1245 | 状态消息（aria-live） |

**资产行布局**：

- 可出售建筑 → 显示当前等级 + "出售建筑 +$退款金额" 按钮
- 可抵押地产 → 显示未抵押 + "抵押 +$抵押金额" 按钮
- 不可操作 → 显示原因（已抵押 / 需遵守平均出售规则 / 同色组仍有建筑 / 当前没有可处置项目）

**响应式**：
- 桌面端：弹窗宽度 620px，摘要双列布局
- 移动端（≤700px）：单列布局，按钮占满宽度，资产区独立滚动

### 4. 交互函数

| 函数 | 文件位置 | 说明 |
|------|---------|------|
| `showDebtReliefModal()` | L2768 | 渲染弹窗内容，实时计算进度 |
| `performDebtReliefAction()` | L2803 | 执行出售/抵押操作，调用进度重评 |
| `resolveDebtReliefProgress()` | L2820 | 每次操作后重评：现金非负→自动完成 / 仍可操作→刷新面板 / 无操作→破产 |

### 5. 控制锁（债务处置期间禁止操作）

| 检查点 | 文件位置 | 变更 |
|--------|---------|------|
| `canCurrentPlayerRoll()` | L1564 | 新增 `!debtReliefState` 条件 |
| `openTradeComposer()` | L3574 | 新增 `if (debtReliefState) return;` |
| `btnTrade` 禁用逻辑 | L3994 | 新增 `Boolean(debtReliefState)` |

### 6. 各债务来源恢复回调

| 债务来源 | 文件位置 | 恢复机制 |
|---------|---------|---------|
| 租金（`handleLandingHuman`） | L2241 | `resumeAfterRent = () => endTurn(isDouble)` |
| 税费（`handleLandingHuman`） | L2274 | `resumeAfterTax = () => endTurn(isDouble)` |
| 卡牌（`handleCard`） | L2501 | `continueCardResolution` 回调，包含位置变化检测 |
| 传送（`handleTeleportClick`） | L2570 | `continueTeleport` 回调 |
| 拍卖（`finalizeAuction`） | L3239 | `resumeAfterAuction = () => endTurn(wasDouble)` |
| `checkAllBankruptcies()` | L1692 | 新增 `resume` 参数，向所有玩家传递回调 |

### 7. 文档更新

- **桌游版大富翁经济系统与规则.md** — 第16节"破产规则"改为"负债与破产规则"，新增真人手动处置流程说明
- **monopoly_review.md** — 新增 correctness fix 条目记录此修复

---

## 新增测试

共 4 个新测试，全部通过（总计 39 个测试）：

| 测试名称 | 文件 |
|---------|------|
| `active debt relief prevents rolling` | turn_and_bankruptcy_test.mjs:L231 |
| `successful human debt repayment resumes the supplied landing flow` | turn_and_bankruptcy_test.mjs:L243 |
| `a manual debt action rechecks repayment immediately` | turn_and_bankruptcy_test.mjs:L261 |
| `debt relief modal has a fixed summary and scrollable asset list` | trade_ui_test.mjs:L39 |

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `monopoly.html` | 修改 | 状态机、UI、回调逻辑 |
| `tests/turn_and_bankruptcy_test.mjs` | 修改 | 新增 3 个测试 |
| `tests/trade_ui_test.mjs` | 修改 | 新增 1 个测试 |
| `桌游版大富翁经济系统与规则.md` | 修改 | 第16节规则更新 |
| `monopoly_review.md` | 修改 | 新增修复记录 |

---

## 验证结果

```
node --test tests/*.mjs          ✔ 39 pass, 0 fail
python -m py_compile monopoly_app.py ✔ 编译通过
node --check <inline-script>     ✔ 语法检查通过
```

---

## 成功标准核对

- [x] 真人玩家完全自主决定出售哪些建筑和抵押哪些地产
- [x] 系统不会替真人自动选择资产
- [x] 合法性限制与现有游戏规则一致（平均出售、同色组抵押限制）
- [x] 偿债成功后原流程准确恢复一次（`resume` 回调单次执行）
- [x] 无法偿债时自动进入破产清算
- [x] AI 回合速度和现有自动处置行为保持稳定
