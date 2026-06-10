import test from 'node:test';
import assert from 'node:assert/strict';
import { loadFunctions } from './helpers/load-game-functions.mjs';

function setup(extra = {}) {
  return loadFunctions(
    [
      'isPlayerActive',
      'normalizeTradeBundle',
      'canCounterTrade',
      'getTradePropertyValue',
      'calculateTradeCashReserve',
      'evaluateTradeBundle',
      'getAITradeProfitThreshold',
      'evaluateTradeProposalForAI',
      'createAICounterProposal',
    ],
    {
      SPACES: [
        null,
        { group: 'brown', price: 600, baseRent: 60 },
        null,
        { group: 'brown', price: 600, baseRent: 60 },
        { group: 'red', price: 1200, baseRent: 120 },
      ],
      COLOR_GROUPS: { brown: [1, 3], red: [4, 5, 6] },
      HOUSE_COST: { brown: 500, red: 1000 },
      RENT_MULTIPLIER: [1, 3, 6, 12, 20],
      houseOwnership: {},
      mortgageStatus: {},
      players: [],
      stalemateState: { tier: 0 },
      calculateRent(pos) {
        return ({ 1: 60, 3: 60, 4: 120 }[pos] || 0);
      },
      ...extra,
    },
  );
}

test('a property completing a color group gets a larger valuation', () => {
  const game = setup();
  const nearMonopoly = { id: 0, money: 5000, properties: [1], bankrupt: false };
  const noProgress = { id: 1, money: 5000, properties: [], bankrupt: false };
  assert.ok(game.getTradePropertyValue(nearMonopoly, 3) > game.getTradePropertyValue(noProgress, 3));
});

test('mortgage status discounts property by the unmortgage burden', () => {
  const game = setup();
  const buyer = { id: 0, money: 5000, properties: [], bankrupt: false };
  const normal = game.getTradePropertyValue(buyer, 1);
  game.mortgageStatus[1] = true;
  assert.ok(game.getTradePropertyValue(buyer, 1) < normal);
});

test('cash reserve includes fixed floor, exposure, and planned development', () => {
  const game = setup({
    calculateRent(pos) { return pos === 4 ? 1800 : 0; },
  });
  const ai = { id: 0, money: 6000, properties: [1, 3], bankrupt: false };
  const opponent = { id: 1, money: 6000, properties: [4], bankrupt: false };
  game.players.push(ai, opponent);
  assert.equal(game.calculateTradeCashReserve(ai), 1800);
});

test('AI rejects a proposal that would break its cash reserve', () => {
  const game = setup();
  const ai = { id: 0, money: 1200, properties: [1], hasGetOutOfJailCard: false, bankrupt: false };
  const other = { id: 1, money: 5000, properties: [3], hasGetOutOfJailCard: false, bankrupt: false };
  game.players.push(ai, other);
  const proposal = {
    initiatorId: 1,
    recipientId: 0,
    offer: { propertyIds: [3], cash: 0, jailCard: false },
    request: { propertyIds: [], cash: 1100, jailCard: false },
    counterCount: 0,
  };
  assert.equal(game.evaluateTradeProposalForAI(proposal, ai).decision, 'reject');
});

test('stalemate tiers lower profit threshold but not cash reserve', () => {
  const game = setup();
  const ai = { id: 0, money: 5000, properties: [], bankrupt: false };
  game.stalemateState.tier = 0;
  const threshold0 = game.getAITradeProfitThreshold();
  const reserve0 = game.calculateTradeCashReserve(ai);
  game.stalemateState.tier = 2;
  assert.ok(game.getAITradeProfitThreshold() < threshold0);
  assert.equal(game.calculateTradeCashReserve(ai), reserve0);
});

test('counteroffers stop after two rounds and never exceed payer cash', () => {
  const game = setup();
  const ai = { id: 0, money: 5000, properties: [1], hasGetOutOfJailCard: false, bankrupt: false };
  const human = { id: 1, money: 300, properties: [3], hasGetOutOfJailCard: false, bankrupt: false };
  game.players.push(ai, human);
  const proposal = {
    initiatorId: 1,
    recipientId: 0,
    offer: { propertyIds: [3], cash: 0, jailCard: false },
    request: { propertyIds: [], cash: 0, jailCard: false },
    counterCount: 2,
  };
  assert.equal(game.canCounterTrade(proposal), false);
  assert.equal(game.createAICounterProposal(proposal, ai, { decision: 'counter', cashAdjustment: 500 }), null);
});

test('when setting is off AI excludes human from trade candidates', () => {
  let humanTargeted = 0;
  const players = [
    { id: 0, isHuman: false, name: 'AI-0' },
    { id: 1, isHuman: true, name: 'Human' },
  ];
  const game = loadFunctions(
    ['attemptAITradeAtTurnStart'],
    {
      allowAIInitiatedHumanTrades: false,
      players,
      getActivePlayers: () => players,
      buildAIProposalForTarget(aiPlayer, target) {
        if (target.isHuman) humanTargeted++;
        return null;
      },
      evaluateTradeBundle() { return 0; },
      consumeTradeWindow() {},
    },
  );
  let doneCalled = 0;
  game.attemptAITradeAtTurnStart(players[0], () => { doneCalled++; });
  assert.equal(humanTargeted, 0);
  assert.equal(doneCalled, 1);
});

test('when setting is off AI can still propose to other AI', () => {
  let aiTargeted = 0;
  const players = [
    { id: 0, isHuman: false, name: 'AI-0' },
    { id: 1, isHuman: true, name: 'Human' },
    { id: 2, isHuman: false, name: 'AI-2' },
  ];
  const game = loadFunctions(
    ['attemptAITradeAtTurnStart'],
    {
      allowAIInitiatedHumanTrades: false,
      players,
      getActivePlayers: () => players,
      buildAIProposalForTarget(aiPlayer, target) {
        if (!target.isHuman) aiTargeted++;
        return null;
      },
      evaluateTradeBundle() { return 0; },
      consumeTradeWindow() {},
    },
  );
  let doneCalled = 0;
  game.attemptAITradeAtTurnStart(players[0], () => { doneCalled++; });
  assert.equal(aiTargeted, 1);
  assert.equal(doneCalled, 1);
});

test('when setting is on AI can propose to human', () => {
  let humanTargeted = 0;
  const players = [
    { id: 0, isHuman: false, name: 'AI-0' },
    { id: 1, isHuman: true, name: 'Human' },
  ];
  const game = loadFunctions(
    ['attemptAITradeAtTurnStart'],
    {
      allowAIInitiatedHumanTrades: true,
      players,
      getActivePlayers: () => players,
      buildAIProposalForTarget(aiPlayer, target) {
        if (target.isHuman) humanTargeted++;
        return null;
      },
      evaluateTradeBundle() { return 0; },
      consumeTradeWindow() {},
    },
  );
  let doneCalled = 0;
  game.attemptAITradeAtTurnStart(players[0], () => { doneCalled++; });
  assert.equal(humanTargeted, 1);
  assert.equal(doneCalled, 1);
});
