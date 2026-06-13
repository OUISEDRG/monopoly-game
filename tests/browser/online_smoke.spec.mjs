import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const root = new URL('../../', import.meta.url);
const read = (path) => fs.readFileSync(new URL(path, root), 'utf8');

const html = read('web/index.html');
const styles = read('web/styles.css');

test('online game page loads board, action, and modal modules', () => {
  for (const path of [
    '/static/js/game-renderer.js',
    '/static/js/actions.js',
    '/static/js/modals.js',
  ]) {
    assert.match(html, new RegExp(`<script src=["']${path}["']></script>`));
  }
});

test('online game shell contains board, player panels, actions, and modal roots', () => {
  for (const id of [
    'game-section',
    'online-board',
    'online-player-list',
    'online-property-list',
    'online-action-bar',
    'online-roll-btn',
    'online-trade-btn',
    'online-modal-root',
    'online-event-log',
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
});

test('online board has stable responsive dimensions', () => {
  assert.match(styles, /\.online-board\s*\{[^}]*aspect-ratio:\s*1\s*\/\s*1/s);
  assert.match(styles, /\.online-cell\s*\{[^}]*min-width:\s*0/s);
  assert.match(styles, /@media\s*\(max-width:\s*760px\)[\s\S]*\.online-game-shell/s);
});

test('renderer builds the 40-space board from server-shaped snapshots', () => {
  const renderer = read('web/js/game-renderer.js');
  assert.match(renderer, /const\s+ONLINE_SPACES\s*=\s*\[/);
  assert.match(renderer, /position:\s*39/);
  assert.match(renderer, /function\s+renderSnapshot\(/);
  assert.match(renderer, /function\s+renderBoard\(/);
  assert.match(renderer, /textContent/g);
});

test('actions send command intents only', () => {
  const actions = read('web/js/actions.js');
  assert.match(actions, /sendCommand\("ROLL_DICE",\s*\{\}\)/);
  assert.match(actions, /sendCommand\("BUY_PROPERTY",\s*\{\}\)/);
  assert.match(actions, /sendCommand\("DECLINE_PROPERTY",\s*\{\}\)/);
  assert.doesNotMatch(actions, /Math\.random|dice\s*:/);
  assert.doesNotMatch(actions, /propertyOwners\s*=|money\s*=/);
});

test('modals expose property, auction, trade, and debt flows', () => {
  const modals = read('web/js/modals.js');
  for (const command of [
    'BUY_PROPERTY',
    'DECLINE_PROPERTY',
    'PLACE_BID',
    'PASS_AUCTION',
    'PROPOSE_TRADE',
    'ACCEPT_TRADE',
    'REJECT_TRADE',
    'COUNTER_TRADE',
    'DEBT_ACTION',
  ]) {
    assert.match(modals, new RegExp(command));
  }
});
