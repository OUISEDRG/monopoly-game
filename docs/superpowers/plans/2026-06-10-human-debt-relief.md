# Human Debt Relief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace automatic asset disposal for indebted human players with a blocking debt-relief panel where they choose which buildings to sell and which properties to mortgage.

**Architecture:** Keep the existing single-file game structure, but separate debt handling into pure eligibility helpers, a single active `debtReliefState`, human UI actions, AI automatic recovery, and final bankruptcy liquidation. Every human debt source supplies a one-shot resume callback so successful repayment returns to the exact suspended game flow without double-advancing the turn.

**Tech Stack:** HTML/CSS, browser JavaScript, Node.js built-in test runner, VM-based function extraction, Python local launcher, in-app browser verification.

---

## File Map

- Modify `monopoly.html`: debt state, eligibility helpers, modal markup/styles, UI actions, bankruptcy split, control locks, and debt-source callbacks.
- Modify `tests/turn_and_bankruptcy_test.mjs`: debt eligibility, human/AI routing, automatic completion, bankruptcy fallback, and one-shot callback tests.
- Modify `tests/trade_ui_test.mjs`: debt modal structure, scrolling, and responsive layout checks.
- Modify `桌游版大富翁经济系统与规则.md`: document manual human debt relief and unchanged AI automation.
- Modify `monopoly_review.md`: record the previous forced-disposal defect, fix, and verification evidence.

### Task 1: Debt-Relief Eligibility Model

**Files:**
- Modify: `monopoly.html:1422-1445`
- Modify: `monopoly.html:2576-2649`
- Test: `tests/turn_and_bankruptcy_test.mjs`

- [ ] **Step 1: Add failing eligibility tests**

Append:

```js
test('debt relief exposes only legal building sales and mortgages', () => {
  const game = loadFunctions(
    ['canSellHouse', 'canMortgage', 'getDebtReliefActions'],
    {
      SPACES: [
        null,
        { group: 'brown', price: 600 },
        null,
        { group: 'brown', price: 600 },
        { group: 'red', price: 1200 },
      ],
      COLOR_GROUPS: { brown: [1, 3], red: [4, 5, 6] },
      HOUSE_COST: { brown: 500, red: 1000 },
      houseOwnership: { 1: 2, 3: 1 },
      mortgageStatus: {},
    },
  );
  const player = { properties: [1, 3, 4], money: -700 };
  const actions = game.getDebtReliefActions(player);
  assert.deepEqual(
    Array.from(actions.sellableBuildings, item => item.pos),
    [1],
  );
  assert.deepEqual(
    Array.from(actions.mortgageableProperties, item => item.pos),
    [4],
  );
});

test('debt relief reports no actions when every asset is blocked', () => {
  const game = loadFunctions(
    ['canSellHouse', 'canMortgage', 'getDebtReliefActions', 'hasDebtReliefActions'],
    {
      SPACES: [null, { group: 'brown', price: 600 }, null, { group: 'brown', price: 600 }],
      COLOR_GROUPS: { brown: [1, 3] },
      HOUSE_COST: { brown: 500 },
      houseOwnership: {},
      mortgageStatus: { 1: true, 3: true },
    },
  );
  const actions = game.getDebtReliefActions({ properties: [1, 3], money: -100 });
  assert.equal(game.hasDebtReliefActions(actions), false);
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
node --test tests/turn_and_bankruptcy_test.mjs
```

Expected: FAIL because `getDebtReliefActions` and `hasDebtReliefActions` do not exist.

- [ ] **Step 3: Add the debt state and pure eligibility helpers**

Add beside the other global state:

```js
let debtReliefState = null;
```

Reset it in `initGame()`:

```js
debtReliefState = null;
```

Add after `sellHouse()`:

```js
function getDebtReliefActions(player) {
  const sellableBuildings = [];
  const mortgageableProperties = [];

  for (const pos of player.properties) {
    if (canSellHouse(player, pos)) {
      sellableBuildings.push({
        pos,
        refund: Math.floor((HOUSE_COST[SPACES[pos].group] || 0) * 0.5),
      });
    }
    if (canMortgage(player, pos)) {
      mortgageableProperties.push({
        pos,
        value: Math.floor(SPACES[pos].price * 0.5),
      });
    }
  }

  return { sellableBuildings, mortgageableProperties };
}

function hasDebtReliefActions(actions) {
  return actions.sellableBuildings.length > 0
    || actions.mortgageableProperties.length > 0;
}
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run:

```powershell
node --test tests/turn_and_bankruptcy_test.mjs
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- monopoly.html tests/turn_and_bankruptcy_test.mjs
git commit -m "feat: model legal human debt relief actions"
```

### Task 2: One-Shot Debt State Machine

**Files:**
- Modify: `monopoly.html:3575-3690`
- Test: `tests/turn_and_bankruptcy_test.mjs`

- [ ] **Step 1: Add failing state-machine tests**

Append:

```js
test('human debt starts manual relief without disposing assets', () => {
  let opened = 0;
  let sold = 0;
  let mortgaged = 0;
  const game = loadFunctions(
    [
      'canSellHouse', 'canMortgage', 'getDebtReliefActions',
      'hasDebtReliefActions', 'startHumanDebtRelief',
      'checkBankruptcy',
    ],
    {
      SPACES: [null, { group: 'brown', price: 600 }],
      COLOR_GROUPS: { brown: [1] },
      HOUSE_COST: { brown: 500 },
      houseOwnership: { 1: 1 },
      mortgageStatus: {},
      debtReliefState: null,
      consumeTradeWindow() {},
      addGameLog() {},
      showDebtReliefModal() { opened++; },
      sellHouse() { sold++; },
      mortgageProperty() { mortgaged++; },
    },
  );
  const player = {
    id: 0, isHuman: true, bankrupt: false,
    money: -200, properties: [1],
  };
  assert.equal(game.checkBankruptcy(player, null, () => {}), true);
  assert.equal(opened, 1);
  assert.equal(sold, 0);
  assert.equal(mortgaged, 0);
  assert.equal(game.debtReliefState.playerId, 0);
});

test('finishing debt relief resumes exactly once', () => {
  let resumed = 0;
  const game = loadFunctions(['finishDebtRelief'], {
    debtReliefState: {
      playerId: 0,
      completed: false,
      resume() { resumed++; },
    },
    document: {
      getElementById() {
        return { classList: { add() {} } };
      },
    },
  });
  game.finishDebtRelief(true);
  game.finishDebtRelief(true);
  assert.equal(resumed, 1);
  assert.equal(game.debtReliefState, null);
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
node --test tests/turn_and_bankruptcy_test.mjs
```

Expected: FAIL because the debt state-machine functions are missing and humans are still auto-disposed.

- [ ] **Step 3: Extract final bankruptcy liquidation**

Move the existing Step 3 portion of `checkBankruptcy()` into:

```js
function finalizePlayerBankruptcy(player, creditor = null) {
  notify(`${player.name} 破产了！资产将被清算...`);
  addGameLog('system', player.name, '宣布破产，资产进入清算');
  const activeCreditor = creditor && creditor !== player && isPlayerActive(creditor)
    ? creditor
    : null;
  const liquidationProperties = activeCreditor ? [] : detachBankruptProperties(player);

  if (activeCreditor) {
    transferBankruptAssetsToCreditor(player, activeCreditor);
    notify(`${activeCreditor.name} 获得了 ${player.name} 的可转移资产。`);
    addGameLog('property', activeCreditor.name, `接收 ${player.name} 的全部地产`);
  } else {
    player.hasGetOutOfJailCard = false;
  }

  eliminatePlayer(player);
  renderBoard();
  updateUI({ refreshBoard: false });

  if (shouldEndGame()) {
    setTimeout(() => endGame(), 800);
    return true;
  }

  const resumeAfterLiquidation = () => {
    if (!gameOver) endTurn(false);
  };
  if (liquidationProperties.length > 0) {
    liquidatePropertiesByAuction(liquidationProperties, resumeAfterLiquidation);
  } else {
    resumeAfterLiquidation();
  }
  return true;
}
```

- [ ] **Step 4: Add human state and AI automatic recovery**

Add:

```js
function startHumanDebtRelief(player, creditor, resume) {
  if (debtReliefState?.playerId === player.id) return;
  debtReliefState = {
    playerId: player.id,
    creditorId: creditor?.id ?? null,
    initialDebt: Math.max(1, Math.abs(player.money)),
    resume: typeof resume === 'function' ? resume : null,
    completed: false,
  };
  consumeTradeWindow();
  addGameLog('system', player.name, `进入债务处置，需筹集 $${Math.abs(player.money)}`);
  showDebtReliefModal();
}

function finishDebtRelief(shouldResume) {
  const state = debtReliefState;
  if (!state || state.completed) return;
  state.completed = true;
  const resume = state.resume;
  debtReliefState = null;
  document.getElementById('debtReliefModal')?.classList.add('hidden');
  if (shouldResume && typeof resume === 'function') resume();
}

function autoResolveAIDebt(player) {
  for (const pos of [...player.properties]) {
    while (player.money < 0 && canSellHouse(player, pos)) {
      sellHouse(player, pos);
    }
  }
  for (const pos of [...player.properties]) {
    if (player.money >= 0) break;
    if (canMortgage(player, pos)) mortgageProperty(player, pos);
  }
  return player.money >= 0;
}
```

Replace `checkBankruptcy` with:

```js
function checkBankruptcy(player, creditor = null, resume = null) {
  if (player.money >= 0 || player.bankrupt) return false;

  if (player.isHuman) {
    const actions = getDebtReliefActions(player);
    if (hasDebtReliefActions(actions)) {
      startHumanDebtRelief(player, creditor, resume);
      return true;
    }
    return finalizePlayerBankruptcy(player, creditor);
  }

  if (autoResolveAIDebt(player)) {
    notify(`${player.name} 通过自动处置资产偿清了债务。`);
    return false;
  }
  return finalizePlayerBankruptcy(player, creditor);
}
```

- [ ] **Step 5: Run the tests and verify GREEN**

Run:

```powershell
node --test tests/turn_and_bankruptcy_test.mjs
```

Expected: all debt and existing bankruptcy tests pass.

- [ ] **Step 6: Commit**

```powershell
git add -- monopoly.html tests/turn_and_bankruptcy_test.mjs
git commit -m "refactor: separate human debt relief from bankruptcy"
```

### Task 3: Debt-Relief Modal and Player Actions

**Files:**
- Modify: `monopoly.html:720-935`
- Modify: `monopoly.html:1180-1300`
- Modify: `monopoly.html:3575-3690`
- Test: `tests/trade_ui_test.mjs`
- Test: `tests/turn_and_bankruptcy_test.mjs`

- [ ] **Step 1: Add failing UI and action tests**

Append to `tests/trade_ui_test.mjs`:

```js
test('debt relief modal has a fixed summary and scrollable asset list', () => {
  for (const id of [
    'debtReliefModal', 'debtReliefTitle', 'debtReliefCash',
    'debtReliefNeeded', 'debtReliefProgress', 'debtReliefAssets',
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(html, /\.debt-relief-assets\s*\{[^}]*overflow-y:\s*auto/s);
  assert.match(html, /@media\s*\(max-width:\s*700px\)[\s\S]*\.debt-relief-card/s);
});
```

Append to `tests/turn_and_bankruptcy_test.mjs`:

```js
test('a manual debt action rechecks repayment immediately', () => {
  let completed = 0;
  const player = { id: 0, money: -200, properties: [1], bankrupt: false };
  const game = loadFunctions(
    ['resolveDebtReliefProgress', 'finishDebtRelief'],
    {
      players: [player],
      debtReliefState: {
        playerId: 0,
        creditorId: null,
        completed: false,
        resume() { completed++; },
      },
      getDebtReliefActions() {
        return { sellableBuildings: [], mortgageableProperties: [] };
      },
      hasDebtReliefActions() { return false; },
      finalizePlayerBankruptcy() {
        throw new Error('must not bankrupt after repayment');
      },
      showDebtReliefModal() {},
      addGameLog() {},
      document: {
        getElementById() {
          return { classList: { add() {} } };
        },
      },
    },
  );
  player.money = 100;
  game.resolveDebtReliefProgress();
  assert.equal(completed, 1);
  assert.equal(game.debtReliefState, null);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
node --test tests/trade_ui_test.mjs tests/turn_and_bankruptcy_test.mjs
```

Expected: FAIL because modal markup, styles, and progress handlers are absent.

- [ ] **Step 3: Add modal markup**

Insert before the trade modal:

```html
<!-- Human Debt Relief -->
<div class="modal-overlay hidden" id="debtReliefModal">
  <div class="modal-card debt-relief-card" role="dialog" aria-modal="true"
       aria-labelledby="debtReliefTitle">
    <div class="modal-title" id="debtReliefTitle">债务处置中心</div>
    <div class="debt-relief-summary">
      <div><span>当前现金</span><strong id="debtReliefCash">$0</strong></div>
      <div><span>仍需筹集</span><strong id="debtReliefNeeded">$0</strong></div>
      <div class="debt-relief-track" aria-hidden="true">
        <div id="debtReliefProgress"></div>
      </div>
    </div>
    <div class="debt-relief-assets" id="debtReliefAssets"></div>
    <div class="trade-error" id="debtReliefStatus" aria-live="polite"></div>
  </div>
</div>
```

- [ ] **Step 4: Add modal styles**

Add:

```css
.debt-relief-card {
  width: min(620px, 94vw);
  max-height: 90vh;
  overflow: hidden;
}

.debt-relief-summary {
  position: sticky;
  top: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid rgba(201,168,76,0.3);
  background: #182435;
}

.debt-relief-summary div:not(.debt-relief-track) {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.debt-relief-summary strong { color: #ff8f83; }
.debt-relief-track {
  grid-column: 1 / -1;
  height: 8px;
  overflow: hidden;
  background: rgba(255,255,255,0.08);
}
.debt-relief-track > div {
  width: 0;
  height: 100%;
  background: var(--gold);
  transition: width 0.2s ease;
}
.debt-relief-assets {
  max-height: min(52vh, 420px);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.debt-relief-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  min-height: 58px;
  padding: 10px 2px;
  border-bottom: 1px solid rgba(201,168,76,0.16);
}
.debt-relief-reason {
  display: block;
  color: rgba(232,213,183,0.55);
  font-size: 0.68rem;
}

@media (max-width: 700px) {
  .debt-relief-card { padding: 16px; max-height: 94vh; }
  .debt-relief-summary { grid-template-columns: 1fr; }
  .debt-relief-track { grid-column: 1; }
  .debt-relief-row { grid-template-columns: 1fr; }
  .debt-relief-row .btn-house { width: 100%; min-height: 40px; }
}
```

- [ ] **Step 5: Add reason, rendering, and action handlers**

Add:

```js
function getDebtReliefBlockReason(player, pos) {
  if (mortgageStatus[pos]) return '已抵押';
  if (houseOwnership[pos] && !canSellHouse(player, pos)) return '需遵守平均出售规则';
  const group = COLOR_GROUPS[SPACES[pos].group] || [];
  if (group.some(id => houseOwnership[id])) return '同色组仍有建筑，不能抵押';
  return '当前没有可处置项目';
}

function showDebtReliefModal() {
  const state = debtReliefState;
  const player = players.find(candidate => candidate.id === state?.playerId);
  if (!state || !player) return;
  const actions = getDebtReliefActions(player);
  const sellable = new Map(actions.sellableBuildings.map(item => [item.pos, item]));
  const mortgageable = new Map(actions.mortgageableProperties.map(item => [item.pos, item]));
  const needed = Math.max(0, -player.money);
  const repaid = Math.max(0, state.initialDebt - needed);
  const progress = Math.min(100, Math.round((repaid / state.initialDebt) * 100));

  document.getElementById('debtReliefTitle').textContent = `${player.name} · 债务处置`;
  document.getElementById('debtReliefCash').textContent = `$${player.money}`;
  document.getElementById('debtReliefNeeded').textContent = `$${needed}`;
  document.getElementById('debtReliefProgress').style.width = `${progress}%`;
  document.getElementById('debtReliefAssets').innerHTML = player.properties.map(pos => {
    const space = SPACES[pos];
    const sale = sellable.get(pos);
    const mortgage = mortgageable.get(pos);
    const action = sale
      ? `<button class="btn-house" onclick="performDebtReliefAction('sell-building',${pos})">出售建筑 +$${sale.refund}</button>`
      : mortgage
        ? `<button class="btn-house" onclick="performDebtReliefAction('mortgage',${pos})">抵押 +$${mortgage.value}</button>`
        : `<span class="debt-relief-reason">${getDebtReliefBlockReason(player, pos)}</span>`;
    return `<div class="debt-relief-row">
      <div>
        <strong>${escapeHTML(space.name)}</strong>
        <span class="debt-relief-reason">${HOUSE_LEVEL_NAMES[houseOwnership[pos] || 0]} · ${mortgageStatus[pos] ? '已抵押' : '未抵押'}</span>
      </div>
      ${action}
    </div>`;
  }).join('');
  document.getElementById('debtReliefModal').classList.remove('hidden');
}

function performDebtReliefAction(type, pos) {
  const state = debtReliefState;
  const player = players.find(candidate => candidate.id === state?.playerId);
  if (!state || !player || player.money >= 0) return;

  if (type === 'sell-building' && canSellHouse(player, pos)) {
    sellHouse(player, pos);
  } else if (type === 'mortgage' && canMortgage(player, pos)) {
    mortgageProperty(player, pos);
  } else {
    document.getElementById('debtReliefStatus').textContent = '该资产当前不可处置。';
    showDebtReliefModal();
    return;
  }
  resolveDebtReliefProgress();
}

function resolveDebtReliefProgress() {
  const state = debtReliefState;
  const player = players.find(candidate => candidate.id === state?.playerId);
  if (!state || !player) return;

  if (player.money >= 0) {
    addGameLog('system', player.name, `完成债务处置，当前现金 $${player.money}`);
    finishDebtRelief(true);
    updateUI();
    return;
  }

  const actions = getDebtReliefActions(player);
  if (!hasDebtReliefActions(actions)) {
    const creditor = players.find(candidate => candidate.id === state.creditorId) || null;
    finishDebtRelief(false);
    finalizePlayerBankruptcy(player, creditor);
    return;
  }
  showDebtReliefModal();
}
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
node --test tests/trade_ui_test.mjs tests/turn_and_bankruptcy_test.mjs
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add -- monopoly.html tests/trade_ui_test.mjs tests/turn_and_bankruptcy_test.mjs
git commit -m "feat: add human debt relief panel"
```

### Task 4: Suspend and Resume Every Human Debt Source

**Files:**
- Modify: `monopoly.html:1480-1484`
- Modify: `monopoly.html:2143-2205`
- Modify: `monopoly.html:2385-2485`
- Modify: `monopoly.html:3016-3036`
- Modify: `monopoly.html:3749-3790`
- Test: `tests/turn_and_bankruptcy_test.mjs`

- [ ] **Step 1: Add failing control-lock and callback tests**

Append:

```js
test('active debt relief prevents rolling', () => {
  const game = loadFunctions(['isPlayerActive', 'canCurrentPlayerRoll'], {
    gameOver: false,
    tradeState: null,
    debtReliefState: { playerId: 0 },
    tradeWindow: { locked: false },
    currentPlayerIndex: 0,
    players: [{ id: 0, isHuman: true, bankrupt: false }],
  });
  assert.equal(game.canCurrentPlayerRoll(), false);
});

test('successful human debt repayment resumes the supplied landing flow', () => {
  let resumed = 0;
  const game = loadFunctions(['finishDebtRelief'], {
    debtReliefState: {
      playerId: 0,
      completed: false,
      resume() { resumed++; },
    },
    document: {
      getElementById() {
        return { classList: { add() {} } };
      },
    },
  });
  game.finishDebtRelief(true);
  assert.equal(resumed, 1);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
node --test tests/turn_and_bankruptcy_test.mjs
```

Expected: rolling is still allowed while debt state exists.

- [ ] **Step 3: Lock controls during debt relief**

Change:

```js
function canCurrentPlayerRoll() {
  const player = players[currentPlayerIndex];
  return !gameOver && isPlayerActive(player) && player.isHuman
    && !tradeWindow.locked && !tradeState && !debtReliefState;
}
```

Add `Boolean(debtReliefState)` to the trade-button disabled expression and guard `openTradeComposer()`:

```js
if (debtReliefState) return;
```

- [ ] **Step 4: Supply resume callbacks for rent and tax**

Replace the human rent branch:

```js
const resumeAfterRent = () => endTurn(isDouble);
if (!checkBankruptcy(player, owner, resumeAfterRent)) resumeAfterRent();
```

Replace the human tax completion:

```js
const resumeAfterTax = () => endTurn(isDouble);
if (!checkBankruptcy(player, null, resumeAfterTax)) resumeAfterTax();
```

- [ ] **Step 5: Supply a single continuation for human cards**

After applying a human card, define:

```js
const continueCardResolution = () => {
  if (player.inJail && !gameOver) {
    handleJailEntry(player, `${title}: ${msg}`);
    return;
  }
  notify(`${title}: ${msg}`);
  addGameLog('card', player.name, `${title}：${msg}`);
  renderBoard();
  updateUI({ refreshBoard: false });
  if (player.position !== oldPos && !gameOver) {
    handleLandingHuman(player, player.position, isDouble, d1, d2);
  } else {
    endTurn(isDouble);
  }
};
if (!checkAllBankruptcies(player, continueCardResolution)) {
  continueCardResolution();
}
```

Change `checkAllBankruptcies` to accept and forward a resume callback:

```js
function checkAllBankruptcies(creditor = null, resume = null) {
  for (const player of [...players]) {
    if (gameOver) return true;
    if (player.money < 0 && checkBankruptcy(player, creditor, resume)) return true;
  }
  return false;
}
```

Keep AI card calls without a callback so AI continues using automatic recovery.

- [ ] **Step 6: Supply teleport and auction callbacks**

In `handleTeleportClick`, wrap the remaining landing logic:

```js
const continueTeleport = () => {
  if (player.position !== oldPos && !gameOver) {
    handleLandingHuman(player, player.position, isDouble, d1, d2);
  } else {
    endTurn(isDouble);
  }
};
if (!checkBankruptcy(player, null, continueTeleport)) continueTeleport();
```

At normal auction completion:

```js
const resumeAfterAuction = () => endTurn(wasDouble);
if (!checkBankruptcy(players[currentPlayerIndex], null, resumeAfterAuction)) {
  resumeAfterAuction();
}
```

- [ ] **Step 7: Run all debt and turn tests**

Run:

```powershell
node --test tests/turn_and_bankruptcy_test.mjs tests/property_and_stalemate_rules_test.mjs
```

Expected: all tests pass with no repeated callbacks.

- [ ] **Step 8: Commit**

```powershell
git add -- monopoly.html tests/turn_and_bankruptcy_test.mjs
git commit -m "fix: resume suspended flows after manual debt relief"
```

### Task 5: Rules, Review Report, and Full Verification

**Files:**
- Modify: `桌游版大富翁经济系统与规则.md`
- Modify: `monopoly_review.md`
- Verify: `monopoly.html`
- Verify: `monopoly_app.py`

- [ ] **Step 1: Update the full rules**

Replace the bankruptcy section with:

```markdown
## 十六、负债与破产规则

真人玩家现金为负时，游戏暂停并打开债务处置中心：

1. 玩家自主选择出售哪些建筑，建筑按建造价50%卖回银行。
2. 玩家自主选择抵押哪些合法地产，获得地价50%的现金。
3. 建筑出售必须遵守平均出售规则；同色组仍有建筑时不能抵押。
4. 现金恢复到0或以上时自动继续原流程。
5. 仍负债且没有合法操作时自动宣布破产。

AI 玩家按相同合法性规则自动出售建筑和抵押地产。

破产后：

- 有明确债权人时，可转移资产归债权人；
- 没有明确债权人时，地产逐块公开拍卖；
- 破产玩家退出后续回合；
- 游戏持续到仅剩一名未破产玩家。
```

- [ ] **Step 2: Update the review report**

Add under correctness fixes:

```markdown
- 修复真人负债时系统强制选择资产的问题：新增阻塞式债务处置中心，由玩家自主出售建筑或抵押地产；偿清后恢复原流程，无合法操作时才自动破产。
```

Add verification coverage for debt-source callbacks, one-shot completion, desktop/mobile layout, and long-list scrolling.

- [ ] **Step 3: Run the complete automated suite**

Run:

```powershell
node --test tests/*.mjs
python -m py_compile monopoly_app.py
$html = Get-Content -Raw -Encoding utf8 monopoly.html
$script = [regex]::Match($html, '<script>([\s\S]*?)</script>').Groups[1].Value
$temp = Join-Path $env:TEMP 'monopoly-inline-check.js'
[IO.File]::WriteAllText($temp, $script, [Text.UTF8Encoding]::new($false))
node --check $temp
git diff --check
```

Expected: all Node tests pass; Python and inline JavaScript compile; no whitespace errors.

- [ ] **Step 4: Perform browser verification**

Start or reuse the local server, then verify:

1. Desktop 1280×720: force a human player to negative cash with one building and one mortgageable property.
2. Confirm no asset is disposed before clicking.
3. Sell the chosen building; confirm cash, level, and remaining debt update.
4. Mortgage the chosen property; confirm automatic close at nonnegative cash and exactly one turn continuation.
5. Repeat with no legal action; confirm automatic bankruptcy.
6. Repeat at 390×844; confirm no horizontal overflow and only the asset list scrolls.
7. Confirm `tab.dev.logs({ levels: ['error', 'warning'] })` returns no entries.

- [ ] **Step 5: Commit**

```powershell
git add -- monopoly.html tests monopoly_review.md '桌游版大富翁经济系统与规则.md'
git commit -m "feat: let human players choose debt relief assets"
```
