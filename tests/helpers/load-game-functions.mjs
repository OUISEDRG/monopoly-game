import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../../monopoly.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1] || '';

function skipQuoted(source, start, quote) {
  for (let i = start + 1; i < source.length; i++) {
    if (source[i] === '\\') i++;
    else if (source[i] === quote) return i + 1;
  }
  throw new Error(`Unclosed ${quote} string`);
}

function skipLineComment(source, start) {
  const end = source.indexOf('\n', start + 2);
  return end < 0 ? source.length : end + 1;
}

function skipBlockComment(source, start) {
  const end = source.indexOf('*/', start + 2);
  if (end < 0) throw new Error('Unclosed block comment');
  return end + 2;
}

const CONTROL_WORDS = new Set(['if', 'while', 'for', 'with', 'switch', 'catch']);
const REGEX_PREFIX_WORDS = new Set([
  'return', 'throw', 'case', 'delete', 'typeof', 'void', 'yield', 'await',
]);
const controlParenCache = new Map();

function getControlParenClosings(source) {
  if (controlParenCache.has(source)) return controlParenCache.get(source);

  const closings = new Set();
  controlParenCache.set(source, closings);
  const parens = [];
  let pendingControl = false;
  let regexAllowed = true;

  for (let i = 0; i < source.length;) {
    const char = source[i];
    const next = source[i + 1];
    if (/\s/.test(char)) {
      i++;
    } else if (char === "'" || char === '"') {
      i = skipQuoted(source, i, char);
      regexAllowed = false;
    } else if (char === '`') {
      i = skipTemplate(source, i);
      regexAllowed = false;
    } else if (char === '/' && next === '/') {
      i = skipLineComment(source, i);
    } else if (char === '/' && next === '*') {
      i = skipBlockComment(source, i);
    } else if (char === '/' && regexAllowed) {
      i = skipRegex(source, i);
      regexAllowed = false;
    } else if (/[A-Za-z_$]/.test(char)) {
      const wordStart = i++;
      while (/[\w$]/.test(source[i] || '')) i++;
      const word = source.slice(wordStart, i);
      pendingControl = CONTROL_WORDS.has(word);
      regexAllowed = REGEX_PREFIX_WORDS.has(word);
    } else if (char === '(') {
      parens.push({ control: pendingControl });
      pendingControl = false;
      regexAllowed = true;
      i++;
    } else if (char === ')') {
      const context = parens.pop();
      if (context?.control) closings.add(i);
      regexAllowed = Boolean(context?.control);
      pendingControl = false;
      i++;
    } else if (/[0-9]/.test(char)) {
      i++;
      while (/[0-9A-Fa-f_xXoObBeE.]/.test(source[i] || '')) i++;
      regexAllowed = false;
    } else {
      regexAllowed = /[({[=,:;!?&|+\-*%^~<>]/.test(char);
      if (!/\s/.test(char)) pendingControl = false;
      i++;
    }
  }

  return closings;
}

function canStartRegex(source, index) {
  let cursor = index - 1;
  while (cursor >= 0 && /\s/.test(source[cursor])) cursor--;
  if (cursor < 0 || /[({[=,:;!?&|+\-*%^~<>]/.test(source[cursor])) return true;
  if (source[cursor] === ')' && getControlParenClosings(source).has(cursor)) return true;
  const word = source.slice(0, cursor + 1).match(/[A-Za-z_$][\w$]*$/)?.[0];
  return REGEX_PREFIX_WORDS.has(word);
}

function skipRegex(source, start) {
  let inClass = false;
  for (let i = start + 1; i < source.length; i++) {
    const char = source[i];
    if (char === '\\') {
      i++;
      continue;
    }
    if (char === '[') inClass = true;
    else if (char === ']') inClass = false;
    else if (char === '/' && !inClass) {
      i++;
      while (/[A-Za-z]/.test(source[i] || '')) i++;
      return i;
    } else if (char === '\n') {
      throw new Error('Unclosed regular expression');
    }
  }
  throw new Error('Unclosed regular expression');
}

function skipTemplateExpression(source, start) {
  let depth = 1;
  for (let i = start; i < source.length;) {
    const char = source[i];
    const next = source[i + 1];
    if (char === "'" || char === '"') i = skipQuoted(source, i, char);
    else if (char === '`') i = skipTemplate(source, i);
    else if (char === '/' && next === '/') i = skipLineComment(source, i);
    else if (char === '/' && next === '*') i = skipBlockComment(source, i);
    else if (char === '/' && canStartRegex(source, i)) i = skipRegex(source, i);
    else {
      if (char === '{') depth++;
      else if (char === '}' && --depth === 0) return i + 1;
      i++;
    }
  }
  throw new Error('Unclosed template interpolation');
}

function skipTemplate(source, start) {
  for (let i = start + 1; i < source.length;) {
    if (source[i] === '\\') i += 2;
    else if (source[i] === '`') return i + 1;
    else if (source[i] === '$' && source[i + 1] === '{') i = skipTemplateExpression(source, i + 2);
    else i++;
  }
  throw new Error('Unclosed template string');
}

function findBalancedEnd(source, start, open, close) {
  let depth = 1;
  for (let i = start + 1; i < source.length;) {
    const char = source[i];
    const next = source[i + 1];
    if (char === "'" || char === '"') i = skipQuoted(source, i, char);
    else if (char === '`') i = skipTemplate(source, i);
    else if (char === '/' && next === '/') i = skipLineComment(source, i);
    else if (char === '/' && next === '*') i = skipBlockComment(source, i);
    else if (char === '/' && canStartRegex(source, i)) i = skipRegex(source, i);
    else {
      if (char === open) depth++;
      else if (char === close && --depth === 0) return i;
      i++;
    }
  }
  throw new Error(`Unclosed ${open}`);
}

function findFunctionStart(source, name) {
  for (let i = 0; i < source.length;) {
    const char = source[i];
    const next = source[i + 1];
    if (char === "'" || char === '"') i = skipQuoted(source, i, char);
    else if (char === '`') i = skipTemplate(source, i);
    else if (char === '/' && next === '/') i = skipLineComment(source, i);
    else if (char === '/' && next === '*') i = skipBlockComment(source, i);
    else if (char === '/' && canStartRegex(source, i)) i = skipRegex(source, i);
    else if (/[A-Za-z_$]/.test(char)) {
      const tokenStart = i++;
      while (/[\w$]/.test(source[i] || '')) i++;
      if (source.slice(tokenStart, i) !== 'function') continue;
      let cursor = i;
      while (/\s/.test(source[cursor] || '')) cursor++;
      const nameStart = cursor;
      if (!/[A-Za-z_$]/.test(source[cursor] || '')) continue;
      cursor++;
      while (/[\w$]/.test(source[cursor] || '')) cursor++;
      if (source.slice(nameStart, cursor) !== name) continue;
      while (/\s/.test(source[cursor] || '')) cursor++;
      if (source[cursor] === '(') return tokenStart;
    } else i++;
  }
  return -1;
}

export function extractFunctionFromSource(source, name) {
  const start = findFunctionStart(source, name);
  if (start < 0) throw new Error(`Missing function: ${name}`);
  const parametersStart = source.indexOf('(', start);
  const parametersEnd = findBalancedEnd(source, parametersStart, '(', ')');
  const bodyStart = source.indexOf('{', parametersEnd + 1);
  if (bodyStart < 0) throw new Error(`Missing function body: ${name}`);
  const bodyEnd = findBalancedEnd(source, bodyStart, '{', '}');
  return source.slice(start, bodyEnd + 1);
}

export function extractFunction(name) {
  return extractFunctionFromSource(script, name);
}

export function loadFunctions(names, context = {}) {
  const sandbox = { console, Math, Set, Map, ...context };
  vm.createContext(sandbox);
  vm.runInContext(names.map(extractFunction).join('\n'), sandbox);
  return sandbox;
}
