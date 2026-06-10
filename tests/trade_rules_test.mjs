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

test('mortgaged property remains tradable when its color group has buildings', () => {
  const game = setup();
  const player = { id: 0, money: 5000, properties: [1, 3], bankrupt: false };
  game.mortgageStatus[1] = true;
  game.houseOwnership[3] = 1;
  assert.equal(game.canTradeProperty(player, 1), true);
});

test('normalization handles malformed and empty bundles', () => {
  const game = setup();
  assert.deepEqual(Array.from(game.normalizeTradeBundle({ propertyIds: '1,3' }).propertyIds), []);
  assert.deepEqual(Array.from(game.normalizeTradeBundle(null).propertyIds), []);
});

test('settlement transfers property, cash, and jail card atomically', () => {
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
  assert.equal(from.money, 100);
});

test('retargeting a draft preserves the offer and clears the old target request', () => {
  const game = loadFunctions(['normalizeTradeBundle', 'createTradeBundle', 'retargetTradeProposal'], {});
  const proposal = {
    id: 8,
    initiatorId: 0,
    recipientId: 1,
    offer: { propertyIds: [1], cash: 500, jailCard: true },
    request: { propertyIds: [3], cash: 200, jailCard: true },
    counterCount: 0,
    status: 'draft',
  };
  const retargeted = game.retargetTradeProposal(proposal, 2, proposal.offer);
  assert.equal(retargeted.recipientId, 2);
  assert.deepEqual(Array.from(retargeted.offer.propertyIds), [1]);
  assert.equal(retargeted.offer.cash, 500);
  assert.deepEqual(Array.from(retargeted.request.propertyIds), []);
  assert.equal(retargeted.request.cash, 0);
  assert.equal(retargeted.request.jailCard, false);
});
