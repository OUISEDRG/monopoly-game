/**
 * storage.js — localStorage 身份管理
 *
 * 提供保存、读取、清除房间身份的接口。
 * 令牌只存 localStorage，不出现在 DOM 或控制台。
 * 容忍损坏的 JSON。
 */

"use strict";

const STORAGE_KEY = "monopoly_identity";

/**
 * 保存身份到 localStorage。
 * @param {{roomCode: string, playerId: string, reconnectToken: string, websocketPath: string}} identity
 */
function saveIdentity(identity) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
  } catch (_e) {
    // localStorage 不可用时静默失败
  }
}

/**
 * 从 localStorage 读取身份。
 * @returns {{roomCode: string, playerId: string, reconnectToken: string, websocketPath: string}|null}
 */
function loadIdentity() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (
      typeof data === "object" &&
      data !== null &&
      typeof data.roomCode === "string" &&
      typeof data.playerId === "string" &&
      typeof data.reconnectToken === "string" &&
      typeof data.websocketPath === "string"
    ) {
      return data;
    }
    return null;
  } catch (_e) {
    // 损坏的 JSON，清除并返回 null
    clearIdentity();
    return null;
  }
}

/**
 * 清除 localStorage 中的身份。
 */
function clearIdentity() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (_e) {
    // 静默失败
  }
}
