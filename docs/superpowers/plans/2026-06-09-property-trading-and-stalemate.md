# Property Trading and Stalemate Prevention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add voluntary property trading for AI and local-human games, adaptive AI negotiation, late-game stalemate relief, and continued play after individual bankruptcy while preserving full-color-group development rules.

**Architecture:** Keep the existing single-file application, but isolate new behavior behind pure trade valuation/validation helpers, one explicit `tradeState`, and one turn-level activity tracker. UI functions read and update that state; only the atomic settlement function may transfer assets. Auction and bankruptcy flows gain completion callbacks so liquidation can finish without ending the whole game.

**Tech Stack:** HTML5, CSS, browser JavaScript, Node.js built-in test runner (`node:test`), Python static launcher, in-app Browser/Playwright verification.

---

## File Structure

- Modify: `monopoly.html`
  - Add trade state, validation, settlement, AI valuation, negotiation, modal UI, turn-window integration, stalemate tracking, bankruptcy elimination, and liquidation auctions.
- Create: `tests/helpers/load-game-functions.mjs`
  - Extract named functions from the inline script and execute them in a controlled VM context for focused unit tests.
- Create: `tests/trade_rules_test.mjs`
  - Validate trade eligibility, proposal validation, and atomic settlement.
- Create: `tests/ai_trade_strategy_test.mjs`
  - Validate AI valuation, cash reserves, accept/reject/counter behavior, and stalemate thresholds.
- Create: `tests/turn_and_bankruptcy_test.mjs`
  - Validate trade-window lifecycle, active-player rotation, liquidation, and final-winner behavior.
- Create: `tests/trade_ui_test.mjs`
  - Static DOM/CSS assertions for the trade modal, controls, hot-seat handoff, and responsive layout.
- Modify: `桌游版大富翁经济系统与规则.md`
  - Document the confirmed trading, stalemate, mortgage-development, and bankruptcy rules.
- Create: `monopoly_review.md`
  - Record discovered defects, implemented corrections, test evidence, and remaining balance risks.

### Task 1: Test Harness and Core Trade Model

**Files:**
- Create: `tests/helpers/load-game-functions.mjs`
- Create: `tests/trade_rules_test.mjs`
- Modify: `monopoly.html:1349-1368`
- Modify: `monopoly.html:2888-2913`

- [ ] **Step 1: Create the inline-function test helper**

```js
// tests/helpers/load-game-functions.mjs
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../../monopoly.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1] || '';

export function extractFunction(name) {
  const start = script.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`Missing function: ${name}`);
  const bodyStart = script.indexOf('{', start);
  let depth = 0;
  let quote = '';
  let escaped = false;
  for (let i = bodyStart; i < script.length; i++) {
    const char = script[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = '';
      continue;
    }
    if (char === "'" || char === '"' || char === '`') {
      quote = char;
      continue;
    }
    if (char === '{') depth++;
    if (char === '}' && --depth === 0) return script.slice(start, i + 1);
  }
  throw new Error(`Unclosed function: ${name}`);
}

export function loadFunctions(names, context = {}) {
  const sandbox = { console, Math, Set, Map, ...context };
  vm.createContext(sandbox);
  vm.runInContext(names.map(extractFunction).join('\n'), sandbox);
  return sandbox;
}
```

- [ ] **Step 2: Write failing tests for trade eligibility and settlement**

```js
// tests/trade_rules_test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadFunctions } from './helpers/load-game-functions.mjs';

function setup() {
  return loadFunctions(
    ['isPlayerActive', 'normalizeTradeBundle', 'canTradeProperty', 'validateTradeProposal', 'executeTradeProposal'],
    {
      SPACES: [null, { group: 'brown', price: 600 }, null, { group: 'brown', price: 600 }],
      COLOR_GROUPS: { brown: [1, 3] },
      houseOwnership: {},
      mortgageStatus: {},
      players: [],
      addGameLog() {},
      renderBoard() {},
      updateUI() {},
    },
  );
}

test('built color groups cannot be traded', () => {
  const game = setup();
  const player = { id: 0, money: 5000, properties: [1, 3], bankrupt: false };
  game.houseOwnership[3] = 1;
  assert.equal(game.canTradeProperty(player, 1), false);
});

test('settlement transfers all assets atomically', () => {
  const game = setup();
  const from = { id: 0, name: '甲', money: 3000, properties: [1], hasGetOutOfJailCard: true, bankrupt: false };
  const to = { id: 1, name: '乙', money: 2000, properties: [3], hasGetOutOfJailCard: false, bankrupt: false };
  game.players.push(from, to);
  const proposal = {
    initiatorId: 0,
    recipientId: 1,
    offer: { propertyIds: [1], cash: 500, jailCard: true },
    request: { propertyIds: [3], cash: 0, jailCard: false },
  };
  assert.deepEqual(game.validateTradeProposal(proposal), { ok: true });
  assert.equal(game.executeTradeProposal(proposal), true);
  assert.deepEqual(from.properties, [3]);
  assert.deepEqual(to.properties, [1]);
  assert.equal(from.money, 2500);
  assert.equal(to.money, 2500);
  assert.equal(from.hasGetOutOfJailCard, false);
  assert.equal(to.hasGetOutOfJailCard, true);
});

test('failed validation does not partially transfer assets', () => {
  const game = setup();
  const from = { id: 0, money: 100, properties: [1], hasGetOutOfJailCard: false, bankrupt: false };
  const to = { id: 1, money: 2000, properties: [3], hasGetOutOfJailCard: false, bankrupt: false };
  game.players.push(from, to);
  const proposal = {
    initiatorId: 0,
    recipientId: 1,
    offer: { propertyIds: [1], cash: 500, jailCard: false },
    request: { propertyIds: [3], cash: 0, jailCard: false },
  };
  assert.equal(game.executeTradeProposal(proposal), false);
  assert.deepEqual(from.properties, [1]);
  assert.deepEqual(to.properties, [3]);
});
```

- [ ] **Step 3: Run the trade tests and verify RED**

Run: `node --test tests/trade_rules_test.mjs`

Expected: FAIL because `isPlayerActive`, `validateTradeProposal`, and `executeTradeProposal` do not exist.

- [ ] **Step 4: Add the core trade state and pure validation helpers**

Add beside the existing game-state variables:

```js
let tradeState = null;
let tradeWindow = { playerId: null, available: false, locked: false };
let nextTradeId = 1;

function isPlayerActive(player) {
  return Boolean(player) && !player.bankrupt;
}

function createTradeBundle() {
  return { propertyIds: [], cash: 0, jailCard: false };
}

function normalizeTradeBundle(bundle) {
  return {
    propertyIds: [...new Set((bundle.propertyIds || []).map(Number))],
    cash: Math.max(0, Math.floor(Number(bundle.cash) || 0)),
    jailCard: Boolean(bundle.jailCard),
  };
}
```

Replace the current trading stub with:

```js
function validateTradeProposal(rawProposal) {
  const proposal = {
    ...rawProposal,
    offer: normalizeTradeBundle(rawProposal.offer || {}),
    request: normalizeTradeBundle(rawProposal.request || {}),
  };
  const from = players.find(player => player.id === proposal.initiatorId);
  const to = players.find(player => player.id === proposal.recipientId);
  if (!isPlayerActive(from) || !isPlayerActive(to) || from === to) return { ok: false, reason: '交易双方无效' };
  if (proposal.offer.cash > from.money || proposal.request.cash > to.money) return { ok: false, reason: '现金不足' };
  if (proposal.offer.jailCard && !from.hasGetOutOfJailCard) return { ok: false, reason: '发起方没有出狱卡' };
  if (proposal.request.jailCard && !to.hasGetOutOfJailCard) return { ok: false, reason: '接收方没有出狱卡' };

  const allIds = [...proposal.offer.propertyIds, ...proposal.request.propertyIds];
  if (new Set(allIds).size !== allIds.length) return { ok: false, reason: '地产重复' };
  if (!proposal.offer.propertyIds.every(pos => canTradeProperty(from, pos))) return { ok: false, reason: '发起方地产不可交易' };
  if (!proposal.request.propertyIds.every(pos => canTradeProperty(to, pos))) return { ok: false, reason: '接收方地产不可交易' };

  const hasAssets = allIds.length > 0 || proposal.offer.cash > 0 || proposal.request.cash > 0
    || proposal.offer.jailCard || proposal.request.jailCard;
  return hasAssets ? { ok: true } : { ok: false, reason: '报价不能为空' };
}

function executeTradeProposal(proposal) {
  const validation = validateTradeProposal(proposal);
  if (!validation.ok) return false;
  const from = players.find(player => player.id === proposal.initiatorId);
  const to = players.find(player => player.id === proposal.recipientId);
  const offer = normalizeTradeBundle(proposal.offer);
  const request = normalizeTradeBundle(proposal.request);

  from.money += request.cash - offer.cash;
  to.money += offer.cash - request.cash;
  from.properties = from.properties.filter(pos => !offer.propertyIds.includes(pos)).concat(request.propertyIds);
  to.properties = to.properties.filter(pos => !request.propertyIds.includes(pos)).concat(offer.propertyIds);
  if (offer.jailCard) {
    from.hasGetOutOfJailCard = false;
    to.hasGetOutOfJailCard = true;
  }
  if (request.jailCard) {
    to.hasGetOutOfJailCard = false;
    from.hasGetOutOfJailCard = true;
  }
  addGameLog('property', from.name, `与 ${to.name} 完成地产交易`);
  renderBoard();
  updateUI({ refreshBoard: false });
  return true;
}
```

Add `bankrupt: false` to each player object created in `startGame()`.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `node --test tests/trade_rules_test.mjs`

Expected: 3 tests pass.

- [ ] **Step 6: Commit the focused change**

```powershell
git add -- monopoly.html tests/helpers/load-game-functions.mjs tests/trade_rules_test.mjs
git commit -m "feat: add atomic property trade rules"
```

### Task 2: AI Valuation, Risk Control, and Counteroffers

**Files:**
- Create: `tests/ai_trade_strategy_test.mjs`
- Modify: `monopoly.html` trading section

- [ ] **Step 1: Write failing AI strategy tests**

```js
// tests/ai_trade_strategy_test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadFunctions } from './helpers/load-game-functions.mjs';

const context = {
  SPACES: [null, { group: 'brown', price: 600, baseRent: 60 }, null, { group: 'brown', price: 600, baseRent: 60 }],
  COLOR_GROUPS: { brown: [1, 3] },
  HOUSE_COST: { brown: 500 },
  RENT_MULTIPLIER: [1, 3, 6, 12, 20],
  houseOwnership: {},
  mortgageStatus: {},
  players: [],
  stalemateState: { tier: 0 },
};

test('property that completes a color group receives the largest bonus', () => {
  const game = loadFunctions(['getTradePropertyValue'], structuredClone(context));
  const buyer = { id: 0, money: 5000, properties: [1], bankrupt: false };
  const plain = { id: 0, money: 5000, properties: [], bankrupt: false };
  assert.ok(game.getTradePropertyValue(buyer, 3) > game.getTradePropertyValue(plain, 3));
});

test('mortgaged property is discounted by its unmortgage cost', () => {
  const game = loadFunctions(['getTradePropertyValue'], structuredClone(context));
  const buyer = { id: 0, money: 5000, properties: [], bankrupt: false };
  const normal = game.getTradePropertyValue(buyer, 1);
  game.mortgageStatus[1] = true;
  assert.ok(game.getTradePropertyValue(buyer, 1) < normal);
});

test('AI rejects a deal that breaks its cash reserve', () => {
  const game = loadFunctions(
    [
      'isPlayerActive',
      'calculateRent',
      'getTradePropertyValue',
      'calculateTradeCashReserve',
      'evaluateTradeBundle',
      'getAITradeProfitThreshold',
      'evaluateTradeProposalForAI',
    ],
    structuredClone(context),
  );
  const ai = { id: 0, money: 1200, properties: [1], hasGetOutOfJailCard: false, bankrupt: false };
  const other = { id: 1, money: 5000, properties: [3], hasGetOutOfJailCard: false, bankrupt: false };
  game.players.push(ai, other);
  const proposal = {
    initiatorId: 1, recipientId: 0,
    offer: { propertyIds: [3], cash: 0, jailCard: false },
    request: { propertyIds: [], cash: 1100, jailCard: false },
    counterCount: 0,
  };
  assert.equal(game.evaluateTradeProposalForAI(proposal, ai).decision, 'reject');
});

test('stalemate tiers lower profit threshold without lowering reserve', () => {
  const game = loadFunctions(['getAITradeProfitThreshold'], structuredClone(context));
  game.stalemateState.tier = 0;
  const normal = game.getAITradeProfitThreshold();
  game.stalemateState.tier = 2;
  assert.ok(game.getAITradeProfitThreshold() < normal);
});
```

- [ ] **Step 2: Run the strategy tests and verify RED**

Run: `node --test tests/ai_trade_strategy_test.mjs`

Expected: FAIL because the AI trade valuation functions do not exist.

- [ ] **Step 3: Implement deterministic valuation and decision functions**

```js
function getTradePropertyValue(player, pos) {
  const space = SPACES[pos];
  const groupPositions = COLOR_GROUPS[space.group] || [];
  const ownedCount = groupPositions.filter(id => player.properties.includes(id)).length;
  const completesGroup = groupPositions.length > 0 && ownedCount + 1 === groupPositions.length;
  const progressRatio = groupPositions.length ? ownedCount / groupPositions.length : 0;
  const rentValue = (space.baseRent || 0) * 4;
  const completionBonus = completesGroup ? space.price * 0.75 : space.price * progressRatio * 0.2;
  const unmortgageCost = mortgageStatus[pos] ? Math.floor(space.price * 0.55) : 0;
  return Math.max(0, Math.round(space.price + rentValue + completionBonus - unmortgageCost));
}

function calculateTradeCashReserve(player) {
  const opponentRent = players
    .filter(other => other !== player && isPlayerActive(other))
    .flatMap(other => other.properties.map(pos => calculateRent(pos, other, 6, 6)))
    .reduce((highest, rent) => Math.max(highest, rent), 0);
  const plannedBuild = Object.entries(COLOR_GROUPS).reduce((highest, [group, positions]) => {
    return positions.every(pos => player.properties.includes(pos))
      ? Math.max(highest, HOUSE_COST[group] || 0)
      : highest;
  }, 0);
  return Math.max(500, Math.floor(player.money * 0.15), opponentRent, plannedBuild);
}

function evaluateTradeBundle(player, bundle) {
  const propertyValue = bundle.propertyIds.reduce((sum, pos) => sum + getTradePropertyValue(player, pos), 0);
  const jailCardValue = bundle.jailCard ? (player.inJail ? 900 : 450) : 0;
  return propertyValue + bundle.cash + jailCardValue;
}

function getAITradeProfitThreshold() {
  return [1.08, 1.04, 1.01][stalemateState.tier] || 1.08;
}

function evaluateTradeProposalForAI(proposal, aiPlayer) {
  const aiReceives = proposal.recipientId === aiPlayer.id ? proposal.offer : proposal.request;
  const aiGives = proposal.recipientId === aiPlayer.id ? proposal.request : proposal.offer;
  const reserve = calculateTradeCashReserve(aiPlayer);
  const cashAfter = aiPlayer.money + aiReceives.cash - aiGives.cash;
  if (cashAfter < reserve) return { decision: 'reject', reason: 'cash-reserve' };

  const receivedValue = evaluateTradeBundle(aiPlayer, aiReceives);
  const givenValue = evaluateTradeBundle(aiPlayer, aiGives);
  const threshold = getAITradeProfitThreshold();
  if (receivedValue >= givenValue * threshold) return { decision: 'accept' };
  if ((proposal.counterCount || 0) < 2 && receivedValue >= givenValue * 0.78) {
    const cashAdjustment = Math.ceil((givenValue * threshold - receivedValue) / 50) * 50;
    return { decision: 'counter', cashAdjustment };
  }
  return { decision: 'reject', reason: 'value' };
}
```

Add:

```js
function createAICounterProposal(proposal, aiPlayer, evaluation) {
  if (evaluation.decision !== 'counter' || !canCounterTrade(proposal)) return null;
  const counter = {
    ...proposal,
    offer: normalizeTradeBundle(proposal.offer),
    request: normalizeTradeBundle(proposal.request),
    counterCount: (proposal.counterCount || 0) + 1,
    status: 'countered',
  };
  const adjustment = Math.max(0, evaluation.cashAdjustment || 0);
  if (proposal.recipientId === aiPlayer.id) {
    const human = players.find(player => player.id === proposal.initiatorId);
    if (human.money < counter.offer.cash + adjustment) return null;
    counter.offer.cash += adjustment;
  } else {
    const human = players.find(player => player.id === proposal.recipientId);
    if (human.money < counter.request.cash + adjustment) return null;
    counter.request.cash += adjustment;
  }
  return counter;
}
```

- [ ] **Step 4: Run both trade suites**

Run: `node --test tests/trade_rules_test.mjs tests/ai_trade_strategy_test.mjs`

Expected: all tests pass.

- [ ] **Step 5: Commit the AI strategy**

```powershell
git add -- monopoly.html tests/ai_trade_strategy_test.mjs
git commit -m "feat: add risk-aware AI trade valuation"
```

### Task 3: Trade Window and Negotiation State Machine

**Files:**
- Create: `tests/turn_and_bankruptcy_test.mjs`
- Modify: `monopoly.html:1863-2001`
- Modify: `monopoly.html` trading section

- [ ] **Step 1: Write failing lifecycle tests**

```js
// tests/turn_and_bankruptcy_test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadFunctions } from './helpers/load-game-functions.mjs';

test('trade window is available before rolling and consumed after submission', () => {
  const game = loadFunctions(['openTradeWindowForPlayer', 'consumeTradeWindow'], {
    tradeWindow: { playerId: null, available: false, locked: false },
  });
  game.openTradeWindowForPlayer({ id: 2 });
  assert.deepEqual(game.tradeWindow, { playerId: 2, available: true, locked: false });
  game.consumeTradeWindow();
  assert.equal(game.tradeWindow.available, false);
});

test('a third counteroffer is rejected', () => {
  const game = loadFunctions(['canCounterTrade'], {});
  assert.equal(game.canCounterTrade({ counterCount: 1 }), true);
  assert.equal(game.canCounterTrade({ counterCount: 2 }), false);
});
```

- [ ] **Step 2: Run the lifecycle tests and verify RED**

Run: `node --test tests/turn_and_bankruptcy_test.mjs`

Expected: FAIL because the trade-window functions do not exist.

- [ ] **Step 3: Implement the state machine**

```js
function openTradeWindowForPlayer(player) {
  tradeWindow = { playerId: player.id, available: true, locked: false };
}

function lockTradeWindow() {
  tradeWindow.locked = true;
  const rollButton = document.getElementById('btnRoll');
  if (rollButton) rollButton.disabled = true;
}

function consumeTradeWindow() {
  tradeWindow.available = false;
  tradeWindow.locked = false;
}

function canCounterTrade(proposal) {
  return (proposal.counterCount || 0) < 2;
}

function createTradeProposal(initiatorId, recipientId, offer, request) {
  return {
    id: nextTradeId++,
    initiatorId,
    recipientId,
    offer: normalizeTradeBundle(offer),
    request: normalizeTradeBundle(request),
    counterCount: 0,
    status: 'draft',
  };
}

function clearTradeState(reason = '') {
  if (reason) addGameLog('system', '', reason);
  tradeState = null;
  tradeWindow.locked = false;
}
```

Guard `rollDice()` with:

```js
if (tradeWindow.locked || tradeState) return;
tradeWindow.available = false;
```

Ensure all accept, reject, cancel, and validation-failure paths call `consumeTradeWindow()` and `clearTradeState()`.

- [ ] **Step 4: Run lifecycle and trade-rule tests**

Run: `node --test tests/turn_and_bankruptcy_test.mjs tests/trade_rules_test.mjs`

Expected: all tests pass.

- [ ] **Step 5: Commit the state machine**

```powershell
git add -- monopoly.html tests/turn_and_bankruptcy_test.mjs
git commit -m "feat: add bounded trade negotiation state"
```

### Task 4: Responsive Trade UI and Hot-Seat Privacy

**Files:**
- Create: `tests/trade_ui_test.mjs`
- Modify: `monopoly.html:690-816`
- Modify: `monopoly.html:1114-1230`
- Modify: `monopoly.html` trading section

- [ ] **Step 1: Write failing static UI tests**

```js
// tests/trade_ui_test.mjs
import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const html = fs.readFileSync(new URL('../monopoly.html', import.meta.url), 'utf8');

test('trade controls and modal exist', () => {
  for (const id of ['btnTrade', 'tradeModal', 'tradeTarget', 'tradeOfferList', 'tradeRequestList', 'btnTradeSubmit']) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
});

test('trade lists scroll and mobile layout collapses', () => {
  assert.match(html, /\.trade-asset-list\s*\{[^}]*overflow-y:\s*auto/s);
  assert.match(html, /@media\s*\(max-width:\s*700px\)[\s\S]*\.trade-columns/s);
});

test('hot-seat trade handoff has a dedicated action', () => {
  assert.match(html, /function showTradeHandoff\(/);
  assert.match(html, /data-pass-purpose=["']trade["']/);
});
```

- [ ] **Step 2: Run the UI tests and verify RED**

Run: `node --test tests/trade_ui_test.mjs`

Expected: FAIL because the trade modal and controls do not exist.

- [ ] **Step 3: Add the trade button, modal, and layout**

Add next to the dice controls:

```html
<button class="btn-roll btn-trade" id="btnTrade" type="button" onclick="openTradeComposer()">交易</button>
```

Add before the game-over overlay:

```html
<div class="modal-overlay hidden" id="tradeModal">
  <div class="modal-card trade-card">
    <div class="modal-title" id="tradeModalTitle">地产交易</div>
    <div class="trade-toolbar">
      <label for="tradeTarget">交易对象</label>
      <select id="tradeTarget"></select>
      <span id="tradeCounterStatus"></span>
    </div>
    <div class="trade-columns">
      <section>
        <h3>你提供</h3>
        <div class="trade-asset-list" id="tradeOfferList"></div>
        <label>现金 <input id="tradeOfferCash" type="number" min="0" step="50" inputmode="numeric"></label>
        <label><input id="tradeOfferCard" type="checkbox"> 出狱卡</label>
      </section>
      <section>
        <h3>你希望获得</h3>
        <div class="trade-asset-list" id="tradeRequestList"></div>
        <label>现金 <input id="tradeRequestCash" type="number" min="0" step="50" inputmode="numeric"></label>
        <label><input id="tradeRequestCard" type="checkbox"> 出狱卡</label>
      </section>
    </div>
    <div class="trade-summary" id="tradeSummary"></div>
    <div class="trade-error" id="tradeError" aria-live="polite"></div>
    <div class="modal-buttons">
      <button class="btn btn-primary" id="btnTradeSubmit">提交报价</button>
      <button class="btn btn-secondary" id="btnTradeCancel">取消</button>
    </div>
  </div>
</div>
```

Add CSS with stable sizing:

```css
.trade-card { width: min(760px, 94vw); max-width: 760px; max-height: 88vh; overflow: hidden; }
.trade-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.trade-asset-list { height: min(32vh, 260px); overflow-y: auto; overscroll-behavior: contain; }
.trade-asset-row { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; min-height: 38px; border-bottom: 1px solid rgba(201,168,76,.16); }
.trade-summary, .trade-error { min-height: 24px; }
@media (max-width: 700px) {
  .trade-card { max-height: 92vh; padding: 18px; }
  .trade-columns { grid-template-columns: 1fr; overflow-y: auto; max-height: 62vh; }
  .trade-asset-list { height: 160px; }
}
```

- [ ] **Step 4: Implement rendering, submission, and hot-seat handoff**

Add these entry points:

```js
function getTradeTargets(player) {
  return getActivePlayers().filter(target => target.id !== player.id);
}

function renderTradeAssetList(containerId, owner, selectedIds) {
  const container = document.getElementById(containerId);
  container.innerHTML = owner.properties.map(pos => {
    const space = SPACES[pos];
    const disabled = !canTradeProperty(owner, pos);
    const checked = selectedIds.includes(pos) ? 'checked' : '';
    const mortgage = mortgageStatus[pos] ? `抵押 · 解押 $${Math.floor(space.price * 0.55)}` : '未抵押';
    return `<label class="trade-asset-row">
      <input type="checkbox" data-property-id="${pos}" ${checked} ${disabled ? 'disabled' : ''}>
      <span>${escapeHTML(space.name)}<small>${mortgage}</small></span>
      <span>$${space.price}</span>
    </label>`;
  }).join('') || '<div class="trade-empty">没有可交易地产</div>';
}

function openTradeComposer() {
  const current = players[currentPlayerIndex];
  if (!tradeWindow.available || tradeWindow.playerId !== current.id || tradeWindow.locked) return;
  const targets = getTradeTargets(current);
  if (targets.length === 0) {
    notify('当前没有可交易对象。');
    return;
  }
  tradeState = createTradeProposal(current.id, targets[0].id, createTradeBundle(), createTradeBundle());
  lockTradeWindow();
  renderTradeComposer(tradeState);
  document.getElementById('tradeModal').classList.remove('hidden');
}

function renderTradeComposer(proposal) {
  const from = players.find(player => player.id === proposal.initiatorId);
  const to = players.find(player => player.id === proposal.recipientId);
  const target = document.getElementById('tradeTarget');
  target.innerHTML = getTradeTargets(from)
    .map(player => `<option value="${player.id}" ${player.id === to.id ? 'selected' : ''}>${escapeHTML(player.name)}</option>`)
    .join('');
  target.disabled = proposal.status !== 'draft';
  renderTradeAssetList('tradeOfferList', from, proposal.offer.propertyIds);
  renderTradeAssetList('tradeRequestList', to, proposal.request.propertyIds);
  document.getElementById('tradeOfferCash').value = proposal.offer.cash;
  document.getElementById('tradeRequestCash').value = proposal.request.cash;
  document.getElementById('tradeOfferCard').checked = proposal.offer.jailCard;
  document.getElementById('tradeOfferCard').disabled = !from.hasGetOutOfJailCard;
  document.getElementById('tradeRequestCard').checked = proposal.request.jailCard;
  document.getElementById('tradeRequestCard').disabled = !to.hasGetOutOfJailCard;
  document.getElementById('tradeCounterStatus').textContent = `还价 ${proposal.counterCount || 0}/2`;
}

function readCheckedProperties(containerId) {
  return [...document.querySelectorAll(`#${containerId} input[data-property-id]:checked`)]
    .map(input => Number(input.dataset.propertyId));
}

function readTradeComposer() {
  return {
    ...tradeState,
    recipientId: Number(document.getElementById('tradeTarget').value),
    offer: {
      propertyIds: readCheckedProperties('tradeOfferList'),
      cash: Number(document.getElementById('tradeOfferCash').value),
      jailCard: document.getElementById('tradeOfferCard').checked,
    },
    request: {
      propertyIds: readCheckedProperties('tradeRequestList'),
      cash: Number(document.getElementById('tradeRequestCash').value),
      jailCard: document.getElementById('tradeRequestCard').checked,
    },
  };
}

function submitTradeComposer() {
  const proposal = readTradeComposer();
  const validation = validateTradeProposal(proposal);
  const error = document.getElementById('tradeError');
  if (!validation.ok) {
    error.textContent = validation.reason;
    return;
  }
  tradeState = { ...proposal, status: 'submitted' };
  consumeTradeWindow();
  document.getElementById('tradeModal').classList.add('hidden');
  routeTradeProposal(tradeState);
}

function showTradeReview(proposal) {
  tradeState = proposal;
  const from = players.find(player => player.id === proposal.initiatorId);
  const to = players.find(player => player.id === proposal.recipientId);
  document.getElementById('tradeModalTitle').textContent = `${from.name} 与 ${to.name} 的报价`;
  renderTradeComposer(proposal);
  document.getElementById('tradeModal').classList.remove('hidden');
}

function showTradeHandoff(targetPlayer, proposal) {
  tradeState = proposal;
  const overlay = document.getElementById('passOverlay');
  overlay.dataset.passPurpose = 'trade';
  overlay.dataset.tradeTargetId = String(targetPlayer.id);
  document.getElementById('passPlayerName').textContent = targetPlayer.name;
  overlay.style.display = 'flex';
  document.getElementById('tradeModal').classList.add('hidden');
}

function acceptTrade() {
  const success = executeTradeProposal(tradeState);
  if (success) recordStrategicActivity();
  document.getElementById('tradeModal').classList.add('hidden');
  clearTradeState(success ? '' : '交易因资产状态变化而取消');
  resumeCurrentTurnAfterTrade();
}

function rejectTrade() {
  addGameLog('system', '', '交易被拒绝');
  document.getElementById('tradeModal').classList.add('hidden');
  clearTradeState();
  resumeCurrentTurnAfterTrade();
}

function counterTrade() {
  if (!canCounterTrade(tradeState)) {
    notify('已达到两轮还价上限。');
    return;
  }
  tradeState = {
    ...readTradeComposer(),
    initiatorId: tradeState.recipientId,
    recipientId: tradeState.initiatorId,
    offer: readTradeComposer().request,
    request: readTradeComposer().offer,
    counterCount: (tradeState.counterCount || 0) + 1,
    status: 'countered',
  };
  routeTradeProposal(tradeState);
}
```

Wire `btnTradeSubmit` to `submitTradeComposer()`, cancellation to `consumeTradeWindow()` plus `clearTradeState()`, and review-mode buttons to `acceptTrade()`, `rejectTrade()`, and `counterTrade()`.

`showTradeHandoff()` must set `passOverlay.dataset.passPurpose = 'trade'`, hide proposal contents, and reveal them only after the target player confirms. Normal turn handoff must set the purpose to `turn`.

- [ ] **Step 5: Run static tests**

Run: `node --test tests/trade_ui_test.mjs`

Expected: all tests pass.

- [ ] **Step 6: Commit the trade UI**

```powershell
git add -- monopoly.html tests/trade_ui_test.mjs
git commit -m "feat: add responsive trade negotiation UI"
```

### Task 5: Human, AI, and AI-to-AI Turn Integration

**Files:**
- Modify: `monopoly.html:1972-2001`
- Modify: `monopoly.html:2075-2208`
- Modify: `monopoly.html` trading section
- Modify: `tests/turn_and_bankruptcy_test.mjs`

- [ ] **Step 1: Add failing integration tests for turn-start behavior**

Append:

```js
test('active human receives one trade window at turn start', () => {
  const game = loadFunctions(['beginPlayerTurn'], {
    tradeWindow: { playerId: null, available: false, locked: false },
    tradeState: null,
    gameMode: 'ai',
    document: { getElementById: () => ({ disabled: false, style: {} }) },
    updateUI() {},
    setStatus() {},
    showPassDevice() {},
    scheduleAITurn() {},
  });
  const human = { id: 0, isHuman: true, bankrupt: false };
  game.beginPlayerTurn(human);
  assert.equal(game.tradeWindow.playerId, 0);
  assert.equal(game.tradeWindow.available, true);
});
```

Add:

```js
test('AI turn invokes one trade attempt before dice scheduling', () => {
  let attempts = 0;
  let rolls = 0;
  const game = loadFunctions(['openTradeWindowForPlayer', 'consumeTradeWindow', 'beginPlayerTurn'], {
    tradeWindow: { playerId: null, available: false, locked: false },
    tradeState: null,
    gameMode: 'ai',
    document: { getElementById: () => ({ disabled: false, style: {} }) },
    updateUI() {},
    setStatus() {},
    showPassDevice() {},
    attemptAITradeAtTurnStart(player, done) { attempts++; done(); },
    setTimeout(fn) { rolls++; fn; },
    aiRollDice() {},
  });
  game.beginPlayerTurn({ id: 1, name: '电脑1', isHuman: false, bankrupt: false });
  assert.equal(attempts, 1);
  assert.equal(rolls, 1);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test tests/turn_and_bankruptcy_test.mjs`

Expected: FAIL because `beginPlayerTurn` and proactive AI trade orchestration do not exist.

- [ ] **Step 3: Centralize turn start**

```js
function beginPlayerTurn(player) {
  openTradeWindowForPlayer(player);
  updateUI();
  if (player.isHuman) {
    if (gameMode === 'human') showPassDevice();
    else {
      document.getElementById('btnRoll').disabled = false;
      setStatus('可先交易，或点击掷骰子开始回合。');
    }
    return;
  }
  setStatus(`${player.name} 正在评估交易...`);
  attemptAITradeAtTurnStart(player, () => {
    consumeTradeWindow();
    setStatus(`${player.name} 思考中...`);
    setTimeout(() => aiRollDice(), 500);
  });
}
```

Update `endTurn()` to rotate only through `isPlayerActive()` players and call `beginPlayerTurn()` exactly once. Doubles do not create a second trade opportunity.

- [ ] **Step 4: Implement proactive AI partner and proposal selection**

Add:

```js
function scoreAITradeTarget(aiPlayer, owner, pos) {
  const group = COLOR_GROUPS[SPACES[pos].group] || [];
  const aiOwned = group.filter(id => aiPlayer.properties.includes(id)).length;
  const ownerOwned = group.filter(id => owner.properties.includes(id)).length;
  const completesAIGroup = aiOwned + 1 === group.length;
  const blocksOwnerGroup = ownerOwned === group.length - 1;
  return (completesAIGroup ? 1000 : 0) + (blocksOwnerGroup ? 350 : 0) + aiOwned * 80;
}

function buildAIProposalForTarget(aiPlayer, owner) {
  const candidate = owner.properties
    .filter(pos => canTradeProperty(owner, pos))
    .map(pos => ({ pos, score: scoreAITradeTarget(aiPlayer, owner, pos) }))
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score)[0];
  if (!candidate) return null;
  const cash = Math.ceil(getTradePropertyValue(aiPlayer, candidate.pos) / 50) * 50;
  if (aiPlayer.money - cash < calculateTradeCashReserve(aiPlayer)) return null;
  return createTradeProposal(
    aiPlayer.id,
    owner.id,
    { propertyIds: [], cash, jailCard: false },
    { propertyIds: [candidate.pos], cash: 0, jailCard: false },
  );
}

function attemptAITradeAtTurnStart(aiPlayer, done) {
  const candidates = getActivePlayers()
    .filter(player => player.id !== aiPlayer.id)
    .map(player => buildAIProposalForTarget(aiPlayer, player))
    .filter(Boolean)
    .sort((a, b) => evaluateTradeBundle(aiPlayer, b.request) - evaluateTradeBundle(aiPlayer, a.request));
  const proposal = candidates[0];
  if (!proposal) {
    done();
    return;
  }
  tradeState = proposal;
  consumeTradeWindow();
  const target = players.find(player => player.id === proposal.recipientId);
  if (target.isHuman) {
    tradeState.resume = done;
    showTradeReview(proposal);
    return;
  }
  resolveAIToAITrade(proposal);
  done();
}

function resolveAIToAITrade(proposal) {
  const target = players.find(player => player.id === proposal.recipientId);
  const evaluation = evaluateTradeProposalForAI(proposal, target);
  if (evaluation.decision === 'accept') {
    executeTradeProposal(proposal);
    recordStrategicActivity();
    return;
  }
  if (evaluation.decision === 'counter') {
    const counter = createAICounterProposal(proposal, target, evaluation);
    if (!counter) return;
    const initiator = players.find(player => player.id === counter.recipientId);
    const response = evaluateTradeProposalForAI(counter, initiator);
    if (response.decision === 'accept') {
      executeTradeProposal(counter);
      recordStrategicActivity();
    }
  }
}
```

`resumeCurrentTurnAfterTrade()` must call `tradeState.resume()` when present; otherwise it restores the current human player's roll button.

- [ ] **Step 5: Fix AI purchase refusal**

Replace the AI refusal branch with:

```js
} else {
  notify(`${player.name} 放弃直接购买 ${space.name}，进入公开拍卖。`);
  startAuction(pos, isDouble);
  return;
}
```

- [ ] **Step 6: Run all current Node tests**

Run: `node --test tests/*.mjs`

Expected: all tests pass.

- [ ] **Step 7: Commit turn integration**

```powershell
git add -- monopoly.html tests/turn_and_bankruptcy_test.mjs
git commit -m "feat: integrate trading into every game mode"
```

### Task 6: Stalemate Tracking and Mortgage Development Rule

**Files:**
- Modify: `monopoly.html:1358-1367`
- Modify: `monopoly.html:1972-2001`
- Modify: `monopoly.html:2212-2238`
- Modify: `monopoly.html:2397-2416`
- Modify: `tests/ai_trade_strategy_test.mjs`

- [ ] **Step 1: Add failing tests for activity tiers and mortgaged groups**

```js
test('three and five inactive rounds produce tier one and tier two', () => {
  const game = loadFunctions(['getStalemateTier'], {});
  assert.equal(game.getStalemateTier(2), 0);
  assert.equal(game.getStalemateTier(3), 1);
  assert.equal(game.getStalemateTier(5), 2);
});

test('a mortgaged property blocks development across its color group', () => {
  const game = loadFunctions(['canBuildHouse'], {
    SPACES: [null, { group: 'brown' }, null, { group: 'brown' }],
    COLOR_GROUPS: { brown: [1, 3] },
    HOUSE_COST: { brown: 500 },
    houseOwnership: {},
    mortgageStatus: { 3: true },
  });
  const player = { money: 5000, properties: [1, 3] };
  assert.equal(game.canBuildHouse(player, 1), false);
});
```

- [ ] **Step 2: Run the strategy suite and verify RED**

Run: `node --test tests/ai_trade_strategy_test.mjs`

Expected: at least the stalemate-tier test fails, and the mortgage test exposes the current missing check.

- [ ] **Step 3: Implement the activity tracker**

```js
let stalemateState = {
  inactiveRounds: 0,
  activityThisRound: false,
  turnsSeen: new Set(),
  tier: 0,
};

function getStalemateTier(inactiveRounds) {
  if (inactiveRounds >= 5) return 2;
  if (inactiveRounds >= 3) return 1;
  return 0;
}

function recordStrategicActivity() {
  stalemateState.activityThisRound = true;
  stalemateState.inactiveRounds = 0;
  stalemateState.tier = 0;
}

function recordCompletedTurn(playerId) {
  stalemateState.turnsSeen.add(playerId);
  const activeIds = players.filter(isPlayerActive).map(player => player.id);
  if (!activeIds.every(id => stalemateState.turnsSeen.has(id))) return;
  if (!stalemateState.activityThisRound) stalemateState.inactiveRounds++;
  stalemateState.tier = getStalemateTier(stalemateState.inactiveRounds);
  stalemateState.turnsSeen.clear();
  stalemateState.activityThisRound = false;
}
```

Call `recordStrategicActivity()` after successful settlement and successful building. Call `recordCompletedTurn()` once when a non-double turn ends. Log only tier transitions.

- [ ] **Step 4: Block all development on mortgaged groups**

Add to `canBuildHouse()` before house-level checks:

```js
if (groupProps.some(groupPos => mortgageStatus[groupPos])) return false;
```

Refactor `aiBuildHouses()` to call `canBuildHouse(player, pos)` before every build, so human and AI development rules cannot drift.

- [ ] **Step 5: Run all strategy and rule tests**

Run: `node --test tests/trade_rules_test.mjs tests/ai_trade_strategy_test.mjs tests/turn_and_bankruptcy_test.mjs`

Expected: all tests pass.

- [ ] **Step 6: Commit the rule correction**

```powershell
git add -- monopoly.html tests/ai_trade_strategy_test.mjs
git commit -m "fix: prevent late-game stalls without relaxing monopolies"
```

### Task 7: Player Elimination and Liquidation Auctions

**Files:**
- Modify: `monopoly.html:2505-2886`
- Modify: `monopoly.html:2915-2999`
- Modify: `tests/turn_and_bankruptcy_test.mjs`

- [ ] **Step 1: Add failing bankruptcy tests**

Append tests that verify:

```js
test('first bankruptcy eliminates one player but does not end a three-player game', () => {
  const game = loadFunctions(['isPlayerActive', 'getActivePlayers', 'shouldEndGame'], { players: [] });
  game.players.push(
    { id: 0, bankrupt: true },
    { id: 1, bankrupt: false },
    { id: 2, bankrupt: false },
  );
  assert.equal(game.getActivePlayers().length, 2);
  assert.equal(game.shouldEndGame(), false);
});

test('game ends when only one active player remains', () => {
  const game = loadFunctions(['isPlayerActive', 'getActivePlayers', 'shouldEndGame'], {
    players: [{ id: 0, bankrupt: true }, { id: 1, bankrupt: false }],
  });
  assert.equal(game.shouldEndGame(), true);
});
```

Append:

```js
test('creditor transfer preserves property ownership list', () => {
  const game = loadFunctions(['transferBankruptAssetsToCreditor'], {
    mortgageStatus: { 1: true },
    houseOwnership: {},
  });
  const debtor = { properties: [1, 3], hasGetOutOfJailCard: true };
  const creditor = { properties: [5], hasGetOutOfJailCard: false };
  game.transferBankruptAssetsToCreditor(debtor, creditor);
  assert.deepEqual(creditor.properties, [5, 1, 3]);
  assert.deepEqual(debtor.properties, []);
  assert.equal(creditor.hasGetOutOfJailCard, true);
});

test('no-creditor liquidation returns every property for auction', () => {
  const game = loadFunctions(['detachBankruptProperties'], {});
  const debtor = { properties: [1, 3, 5] };
  assert.deepEqual(game.detachBankruptProperties(debtor), [1, 3, 5]);
  assert.deepEqual(debtor.properties, []);
});
```

- [ ] **Step 2: Run the bankruptcy tests and verify RED**

Run: `node --test tests/turn_and_bankruptcy_test.mjs`

Expected: FAIL because active-player and continued-game helpers are missing.

- [ ] **Step 3: Add active-player and winner helpers**

```js
function getActivePlayers() {
  return players.filter(isPlayerActive);
}

function shouldEndGame() {
  return getActivePlayers().length <= 1;
}

function getFinalWinner() {
  return getActivePlayers()[0] || players.reduce((best, player) => player.money > best.money ? player : best);
}
```

Update player panels, auctions, trades, and turn rotation to exclude bankrupt players.

- [ ] **Step 4: Refactor auction completion**

Extend auction state with an optional callback:

```js
function startAuction(pos, isDouble, options = {}) {
  const eligiblePlayers = options.eligiblePlayers || getActivePlayers();
  auctionState = {
    pos,
    highestBid: 100,
    highestBidder: null,
    biddingPlayerIndex: 0,
    activeBidderIds: eligiblePlayers
      .filter(player => player.money >= 100)
      .map(player => player.id),
    aiMaxBidByPlayer: {},
    isDouble,
    onComplete: options.onComplete || null,
  };
  for (const player of eligiblePlayers) {
    if (!player.isHuman) auctionState.aiMaxBidByPlayer[player.id] = getAIAuctionMaxBid(player, pos);
  }
  showNextAuctionBidder();
}
```

At the end of `finalizeAuction()`:

```js
const completion = auctionState.onComplete;
auctionState = null;
if (completion) completion();
else endTurn(wasDouble);
```

Capture `wasDouble` and `completion` before clearing state.

- [ ] **Step 5: Replace immediate game-over bankruptcy**

Implement:

```js
function eliminatePlayer(player) {
  player.bankrupt = true;
  player.inJail = false;
  player.money = 0;
  if (tradeState && [tradeState.initiatorId, tradeState.recipientId].includes(player.id)) {
    clearTradeState('交易因玩家破产而取消');
  }
}

function liquidatePropertiesByAuction(propertyIds, done) {
  const queue = [...propertyIds];
  const next = () => {
    if (queue.length === 0) {
      done();
      return;
    }
    startAuction(queue.shift(), false, { eligiblePlayers: getActivePlayers(), onComplete: next });
  };
  next();
}
```

`checkBankruptcy(player, creditor)` must:

1. Keep the existing building-sale and mortgage attempts.
2. Mark the player eliminated only if debt remains.
3. Transfer all properties to an active creditor when supplied.
4. Otherwise remove the properties from the debtor and auction them sequentially.
5. Call `endGame()` only when `shouldEndGame()` is true.
6. Otherwise resume at the next active player's turn after liquidation finishes.

Use these transfer helpers:

```js
function transferBankruptAssetsToCreditor(debtor, creditor) {
  creditor.properties.push(...debtor.properties);
  debtor.properties = [];
  if (debtor.hasGetOutOfJailCard) {
    creditor.hasGetOutOfJailCard = true;
    debtor.hasGetOutOfJailCard = false;
  }
}

function detachBankruptProperties(debtor) {
  const properties = [...debtor.properties];
  debtor.properties = [];
  return properties;
}
```

- [ ] **Step 6: Update `endGame()` to use the final active winner**

Replace the cash-only winner reduction with:

```js
const winner = getFinalWinner();
```

Show eliminated players visually dimmed and label them“已破产”.

- [ ] **Step 7: Run bankruptcy and auction regressions**

Run:

```powershell
node --test tests/turn_and_bankruptcy_test.mjs
node --test tests/*.mjs
```

Expected: all tests pass; no auction test hangs.

- [ ] **Step 8: Commit bankruptcy continuation**

```powershell
git add -- monopoly.html tests/turn_and_bankruptcy_test.mjs
git commit -m "fix: continue play after individual bankruptcy"
```

### Task 8: Documentation, Full Regression, and Browser UX Verification

**Files:**
- Modify: `桌游版大富翁经济系统与规则.md`
- Create: `monopoly_review.md`
- Modify: `monopoly.html:1124-1128`

- [ ] **Step 1: Update the visible and full rules**

Change the compact in-game rules to include:

```html
完整同色组且无抵押才可开发 · 每回合掷骰前可交易一次 · 交易最多还价2轮 · 玩家破产后退出，最后存活者获胜
```

Add this rules section:

```markdown
## 地产交易

- 每位玩家只能在自己回合开始、掷骰前发起一次交易。
- 可交换地产、现金和出狱免费卡。
- 有建筑的地产及其同色组不能交易；抵押地产可以交易并保留抵押状态。
- 每笔交易最多还价两轮，接受前会再次校验双方资产。
- 真人热座交易在每次查看报价前交接设备。

## 后期防僵局

- 连续3个完整轮次没有成交或建造时，AI小幅降低交易利润要求。
- 连续5个完整轮次没有成交或建造时，AI进一步降低利润要求。
- AI现金安全线不随防僵局档位降低，系统不会强制交换或收回地产。

## 开发与破产补充

- 必须持有完整同色组，且该组没有任何抵押地产，才能开发。
- 玩家破产后退出后续回合；有债权人时资产转给债权人。
- 没有债权人时，地产逐块公开拍卖。
- 游戏持续到仅剩一名未破产玩家。
```

- [ ] **Step 2: Write the review report**

Create `monopoly_review.md` with these sections:

```markdown
# Monopoly Mini-game Review

## Correctness Fixes
## Performance Optimizations
## Functional Test Coverage
## Edge Cases
## UX Evaluation
## Remaining Balance Risks
## Verification Evidence
```

Record concrete before/after behavior and exact commands run. Note that AI candidate generation is bounded to one best proposal per opponent and avoids exhaustive asset-combination search.

- [ ] **Step 3: Run automated verification**

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

Expected: all Node tests pass, Python compilation passes, inline JavaScript syntax passes, and `git diff --check` reports no whitespace errors.

- [ ] **Step 4: Start or restart the game server**

Run:

```powershell
python -u monopoly_app.py
```

Use a hidden background process if the launcher blocks the terminal. Record the actual localhost URL.

- [ ] **Step 5: Verify AI-game workflows in the in-app Browser**

Check desktop `1440x900` and mobile `390x844`:

1. Trade button is enabled before rolling and disabled after rolling.
2. Human can compose an offer with property, cash, and an available jail card.
3. AI accepts, rejects, or counters without exceeding two counters.
4. Trade lists scroll without moving the board.
5. Long property names, mortgage badges, and cash amounts do not overflow.
6. Successful trade updates both property panels and logs.
7. AI refusal to buy starts an auction.
8. A mortgaged color group cannot build.

- [ ] **Step 6: Verify local-human workflows**

Check:

1. Initiator composes a proposal before rolling.
2. Device handoff hides proposal details.
3. Recipient can accept, reject, or counter.
4. Each counter requires another private handoff.
5. Third counter is unavailable.
6. Trade completion returns control to the original player's unrolled turn.

- [ ] **Step 7: Verify bankruptcy continuation and UX timing**

Use browser state injection or a deterministic fixture to verify:

1. First bankrupt player is marked eliminated.
2. Remaining players continue taking turns.
3. Creditor receives debtor properties when applicable.
4. No-creditor properties auction sequentially.
5. Only the last active player triggers the game-over overlay.
6. AI-to-AI negotiation completes promptly and never blocks the UI for more than one second without status feedback.

- [ ] **Step 8: Commit documentation and verified integration**

```powershell
git add -- monopoly.html '桌游版大富翁经济系统与规则.md' monopoly_review.md tests
git commit -m "docs: record trading rules and verification"
```

## Final Self-Review Checklist

- [ ] Every confirmed design requirement maps to a task above.
- [ ] Full-color-group ownership remains mandatory for development.
- [ ] AI and human games share one settlement and validation path.
- [ ] Two-counter limit is enforced in state logic, not only hidden in UI.
- [ ] Stalemate adjustment changes only AI profit threshold.
- [ ] Cash reserve remains unchanged at every stalemate tier.
- [ ] Bankrupt players are excluded from turns, auctions, and trades.
- [ ] No-creditor liquidation cannot accidentally call normal `endTurn()` between property auctions.
- [ ] Existing jail, auction, logging, penalty-notice, and dice-animation tests remain green.
