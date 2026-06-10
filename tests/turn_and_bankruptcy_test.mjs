import test from 'node:test';
import assert from 'node:assert/strict';
import { loadFunctions } from './helpers/load-game-functions.mjs';

test('trade window opens once before rolling and can be consumed', () => {
  const game = loadFunctions(
    ['openTradeWindowForPlayer', 'consumeTradeWindow'],
    { tradeWindow: { playerId: null, available: false, locked: false } },
  );
  game.openTradeWindowForPlayer({ id: 2 });
  assert.equal(game.tradeWindow.playerId, 2);
  assert.equal(game.tradeWindow.available, true);
  game.consumeTradeWindow();
  assert.equal(game.tradeWindow.available, false);
});

test('trade window lock prevents rolling', () => {
  const game = loadFunctions(['isPlayerActive', 'canCurrentPlayerRoll'], {
    gameOver: false,
    tradeState: { id: 1 },
    tradeWindow: { locked: true },
    currentPlayerIndex: 0,
    players: [{ isHuman: true, bankrupt: false }],
  });
  assert.equal(game.canCurrentPlayerRoll(), false);
});

test('human-versus-human turn starts without pass-device handoff', () => {
  let passDeviceCalls = 0;
  let status = '';
  const elements = {
    btnRoll: { disabled: true },
  };
  const game = loadFunctions(['beginPlayerTurn'], {
    gameMode: 'human',
    document: {
      getElementById(id) {
        return elements[id];
      },
    },
    openTradeWindowForPlayer() {},
    updateUI() {},
    showPassDevice() { passDeviceCalls++; },
    setStatus(message) { status = message; },
  });

  game.beginPlayerTurn({ id: 1, isHuman: true });

  assert.equal(passDeviceCalls, 0);
  assert.equal(elements.btnRoll.disabled, false);
  assert.match(status, /掷骰子开始回合/);
});

test('counter limit is enforced by state rather than UI', () => {
  const game = loadFunctions(['canCounterTrade'], {});
  assert.equal(game.canCounterTrade({ counterCount: 1 }), true);
  assert.equal(game.canCounterTrade({ counterCount: 2 }), false);
});

test('cancelling a counteroffer resumes the suspended turn', () => {
  let resumed = 0;
  let windowConsumed = 0;
  const game = loadFunctions(['cancelTrade'], {
    tradeState: { status: 'draft', counterCount: 1, resume() { resumed++; } },
    document: {
      getElementById() {
        return { classList: { add() {} } };
      },
    },
    consumeTradeWindow() { windowConsumed++; },
    updateUI() {},
    setStatus() {},
  });
  game.cancelTrade();
  assert.equal(resumed, 1);
  assert.equal(windowConsumed, 1);
  assert.equal(game.tradeState, null);
});

test('first bankruptcy does not end a three-player game', () => {
  const game = loadFunctions(
    ['isPlayerActive', 'getActivePlayers', 'shouldEndGame'],
    {
      players: [
        { id: 0, bankrupt: true },
        { id: 1, bankrupt: false },
        { id: 2, bankrupt: false },
      ],
    },
  );
  assert.equal(game.getActivePlayers().length, 2);
  assert.equal(game.shouldEndGame(), false);
});

test('game ends when only one active player remains', () => {
  const game = loadFunctions(
    ['isPlayerActive', 'getActivePlayers', 'shouldEndGame'],
    {
      players: [
        { id: 0, bankrupt: true },
        { id: 1, bankrupt: false },
      ],
    },
  );
  assert.equal(game.shouldEndGame(), true);
});

test('creditor receives all transferable assets from a bankrupt player', () => {
  const game = loadFunctions(['transferBankruptAssetsToCreditor'], {});
  const debtor = {
    properties: [1, 3],
    hasGetOutOfJailCard: true,
  };
  const creditor = {
    properties: [5],
    hasGetOutOfJailCard: false,
  };
  game.transferBankruptAssetsToCreditor(debtor, creditor);
  assert.deepEqual(Array.from(creditor.properties), [5, 1, 3]);
  assert.deepEqual(Array.from(debtor.properties), []);
  assert.equal(creditor.hasGetOutOfJailCard, true);
  assert.equal(debtor.hasGetOutOfJailCard, false);
});

test('no-creditor liquidation detaches every property for auction', () => {
  const game = loadFunctions(['detachBankruptProperties'], {});
  const debtor = { properties: [1, 3, 5] };
  assert.deepEqual(Array.from(game.detachBankruptProperties(debtor)), [1, 3, 5]);
  assert.deepEqual(Array.from(debtor.properties), []);
});

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
      updateUI() {},
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

test('AI skips trade evaluation when setting off and no AI opponent', () => {
  let tradeAttempted = false;
  let rollScheduled = false;
  const players = [
    { id: 0, isHuman: false, name: 'AI' },
    { id: 1, isHuman: true, name: 'Human' },
  ];
  const game = loadFunctions(
    ['beginPlayerTurn'],
    {
      allowAIInitiatedHumanTrades: false,
      players,
      getActivePlayers: () => players,
      openTradeWindowForPlayer() {},
      consumeTradeWindow() {},
      updateUI() {},
      setStatus() {},
      attemptAITradeAtTurnStart() { tradeAttempted = true; },
      aiRollDice() { rollScheduled = true; },
      setTimeout(fn, ms) { fn(); return 0; },
    },
  );
  game.beginPlayerTurn(players[0]);
  assert.equal(tradeAttempted, false);
  assert.equal(rollScheduled, true);
});

test('AI evaluates trade when setting off but has AI opponent', () => {
  let tradeAttempted = false;
  const players = [
    { id: 0, isHuman: false, name: 'AI-0' },
    { id: 1, isHuman: true, name: 'Human' },
    { id: 2, isHuman: false, name: 'AI-2' },
  ];
  const game = loadFunctions(
    ['beginPlayerTurn'],
    {
      allowAIInitiatedHumanTrades: false,
      players,
      getActivePlayers: () => players,
      openTradeWindowForPlayer() {},
      updateUI() {},
      setStatus() {},
      attemptAITradeAtTurnStart() { tradeAttempted = true; },
    },
  );
  game.beginPlayerTurn(players[0]);
  assert.equal(tradeAttempted, true);
});

test('AI debt resolution sells houses across multiple scan rounds', () => {
  // 复现：平均出售规则下卖房需要多轮扫描
  // [4,4] → 卖 A(4→3, 停止)→ 卖 B(4→3, maxHouses 降为3, A 又可卖)
  const game = loadFunctions(
    ['autoResolveAIDebt', 'canSellHouse', 'sellHouse', 'canMortgage', 'mortgageProperty'],
    {
      SPACES: [
        null,
        { group: 'brown', price: 600, baseRent: 60 },
        null,
        { group: 'brown', price: 600, baseRent: 60 },
      ],
      COLOR_GROUPS: { brown: [1, 3] },
      HOUSE_COST: { brown: 100 },
      houseOwnership: { 1: 4, 3: 4 },
      mortgageStatus: {},
      notify() {},
      addGameLog() {},
      renderBoard() {},
      updateUI() {},
      HOUSE_LEVEL_NAMES: ['空地', '1幢', '2幢', '3幢', '4幢'],
    },
  );
  const player = { money: -150, properties: [1, 3], bankrupt: false };
  const result = game.autoResolveAIDebt(player);
  // 每栋半价 $50，卖 3 栋即可偿清 $150（停在第 4 栋前）
  assert.equal(result, true, '应通过多轮卖房成功偿债');
  assert.ok(player.money >= 0, `资金应为非负，实际: ${player.money}`);
  const totalHouses = (game.houseOwnership[1] || 0) + (game.houseOwnership[3] || 0);
  assert.ok(totalHouses < 8, '至少卖出了一些房子（从 8 栋减少）');
});
