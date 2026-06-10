import test from 'node:test';
import assert from 'node:assert/strict';
import { loadFunctions } from './helpers/load-game-functions.mjs';

test('a mortgage anywhere in a color group blocks human development', () => {
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

test('AI development uses the same mortgage restriction as human development', () => {
  const game = loadFunctions(['canBuildHouse', 'aiBuildHouses'], {
    SPACES: [null, { group: 'brown', name: 'A' }, null, { group: 'brown', name: 'B' }],
    COLOR_GROUPS: { brown: [1, 3] },
    HOUSE_COST: { brown: 500 },
    HOUSE_LEVEL_NAMES: ['空地', '房屋'],
    houseOwnership: {},
    mortgageStatus: { 3: true },
    notify() {},
    addGameLog() {},
  });
  const player = { name: 'AI', money: 5000, properties: [1, 3] };
  game.aiBuildHouses(player);
  assert.deepEqual(game.houseOwnership, {});
  assert.equal(player.money, 5000);
});

test('AI refusal to buy an unowned property starts an auction', () => {
  const calls = [];
  const game = loadFunctions(['handleLandingAI'], {
    SPACES: [null, { type: 'property', name: 'A', group: 'brown', price: 600 }],
    COLOR_GROUPS: { brown: [1, 3] },
    houseOwnership: {},
    freeParkingMoney: 0,
    getOwner() { return null; },
    startAuction(pos, isDouble) { calls.push([pos, isDouble]); },
    notify() {},
    addGameLog() {},
    aiBuildHouses() { throw new Error('auction must suspend landing resolution'); },
    checkBankruptcy() {},
    endTurn() { throw new Error('auction must own turn completion'); },
  });
  const player = { id: 1, name: 'AI', money: 650, properties: [] };
  game.handleLandingAI(player, 1, false, 2, 3);
  assert.deepEqual(calls, [[1, false]]);
  assert.deepEqual(player.properties, []);
});

test('stalemate tier advances only after every active player completes a quiet round', () => {
  const game = loadFunctions(
    ['isPlayerActive', 'getActivePlayers', 'getStalemateTier', 'recordCompletedTurn'],
    {
      players: [
        { id: 0, bankrupt: false },
        { id: 1, bankrupt: false },
        { id: 2, bankrupt: true },
      ],
      stalemateState: {
        inactiveRounds: 2,
        activityThisRound: false,
        turnsSeen: new Set(),
        tier: 0,
      },
      addGameLog() {},
    },
  );
  game.recordCompletedTurn(0);
  assert.equal(game.stalemateState.inactiveRounds, 2);
  game.recordCompletedTurn(1);
  assert.equal(game.stalemateState.inactiveRounds, 3);
  assert.equal(game.stalemateState.tier, 1);
});

test('strategic activity resets stalemate pressure immediately', () => {
  const game = loadFunctions(['recordStrategicActivity'], {
    stalemateState: {
      inactiveRounds: 5,
      activityThisRound: false,
      turnsSeen: new Set([0]),
      tier: 2,
    },
  });
  game.recordStrategicActivity();
  assert.equal(game.stalemateState.inactiveRounds, 0);
  assert.equal(game.stalemateState.tier, 0);
  assert.equal(game.stalemateState.activityThisRound, true);
});
