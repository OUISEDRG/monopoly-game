import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const html = fs.readFileSync(new URL('../monopoly.html', import.meta.url), 'utf8');

test('trade controls and modal exist', () => {
  for (const id of [
    'btnTrade', 'tradeModal', 'tradeTarget', 'tradeOfferList',
    'tradeRequestList', 'btnTradeSubmit', 'btnTradeAccept',
    'btnTradeCounter', 'btnTradeReject',
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
});

test('trade asset lists scroll and collapse on mobile', () => {
  assert.match(html, /\.trade-asset-list\s*\{[^}]*overflow-y:\s*auto/s);
  assert.match(html, /@media\s*\(max-width:\s*700px\)[\s\S]*\.trade-columns/s);
});

test('three-column board tightens before desktop overflow', () => {
  assert.match(
    html,
    /@media\s*\(max-width:\s*1350px\)[\s\S]*?\.game-wrapper\s*\{[^}]*gap:\s*16px[\s\S]*?\.side-panel,[\s\S]*?\.right-panel\s*\{[^}]*width:\s*240px/s,
  );
});

test('hot-seat handoff distinguishes trade from normal turn passing', () => {
  assert.match(html, /function showTradeHandoff\(/);
  assert.match(html, /passPurpose\s*=\s*['"]trade['"]/);
});

test('changing the trade target refreshes the draft', () => {
  assert.match(html, /id=["']tradeTarget["'][^>]*onchange=["']changeTradeTarget\(\)/);
  assert.match(html, /function changeTradeTarget\(\)/);
});

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

test('AI trade setting checkbox exists in setup overlay', () => {
  assert.match(html, /id=["']allowAITradeCheck["']/);
  assert.match(html, /id=["']aiTradeSetting["']/);
  assert.match(html, /允许 AI 主动向我报价/);
});
