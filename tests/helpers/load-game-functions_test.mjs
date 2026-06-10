import test from 'node:test';
import assert from 'node:assert/strict';
import { extractFunctionFromSource } from './load-game-functions.mjs';

test('extracts a function after destructured and object default parameters', () => {
  const source = `function sample({ value } = { value: 2 }, options = { nested: { enabled: true } }) {
    return value + Number(options.nested.enabled);
  }`;
  assert.match(extractFunctionFromSource(source, 'sample'), /return value/);
});

test('ignores braces in comments and regular expression literals', () => {
  const source = `function sample(value) {
    // This brace is not code: }
    /* Nor are these: { } */
    return /[{}]/.test(value);
  }
  function after() {}`;
  const extracted = extractFunctionFromSource(source, 'sample');
  assert.match(extracted, /\/\[\{\}\]\//);
  assert.doesNotMatch(extracted, /function after/);
});

test('tracks nested templates and regex after control conditions', () => {
  const source = `function sample(value) {
    if (String(value).includes(')')) /}/.test(value);
    return \`prefix \${value ? \`\${value} }\` : '{'} suffix\`;
  }
  function after() {}`;
  const extracted = extractFunctionFromSource(source, 'sample');
  assert.match(extracted, /prefix/);
  assert.doesNotMatch(extracted, /function after/);
});

test('ignores function declarations inside comments', () => {
  const source = `// function sample(fake) { return 'line'; }
  /* function sample(fake) { return 'block'; } */
  function sample(value) { return value; }`;
  const extracted = extractFunctionFromSource(source, 'sample');
  assert.match(extracted, /return value/);
  assert.doesNotMatch(extracted, /line|block/);
});
