/**
 * network.js — WebSocket 连接、自动重连和消息分发
 *
 * 提供 connect / sendCommand / disconnect 接口。
 * 自动重连退避序列：1、2、4、8、15 秒，成功后重置。
 * 令牌不出现在 DOM、控制台或错误文本。
 */

"use strict";

var Network = (function () {
  var BACKOFF_SEQUENCE = [1000, 2000, 4000, 8000, 15000];
  var backoffIndex = 0;
  var ws = null;
  var reconnectTimer = null;
  var onSnapshot = null;
  var onCommandResult = null;
  var onConnectionChange = null;
  var onPrivateEvent = null;
  var identity = null;

  function connect(id, callbacks) {
    identity = id;
    onSnapshot = callbacks.onSnapshot || null;
    onCommandResult = callbacks.onCommandResult || null;
    onConnectionChange = callbacks.onConnectionChange || null;
    onPrivateEvent = callbacks.onPrivateEvent || null;

    _openSocket();
  }

  function _openSocket() {
    if (!identity) return;

    var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    var url =
      protocol +
      "//" +
      window.location.host +
      identity.websocketPath +
      "?playerId=" +
      encodeURIComponent(identity.playerId) +
      "&token=" +
      encodeURIComponent(identity.reconnectToken);

    ws = new WebSocket(url);

    ws.onopen = function () {
      backoffIndex = 0;
      if (onConnectionChange) onConnectionChange(true);
    };

    ws.onmessage = function (event) {
      var msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }

      if (msg.type === "state_snapshot" && onSnapshot) {
        onSnapshot(msg);
      } else if (msg.type === "command_result" && onCommandResult) {
        onCommandResult(msg);
      } else if (msg.type && onPrivateEvent) {
        onPrivateEvent(msg);
      }
    };

    ws.onclose = function () {
      ws = null;
      if (onConnectionChange) onConnectionChange(false);
      _scheduleReconnect();
    };

    ws.onerror = function () {
      // onclose will fire after this
    };
  }

  function _scheduleReconnect() {
    if (reconnectTimer) return;
    if (!identity) return;

    var delay = BACKOFF_SEQUENCE[backoffIndex] || BACKOFF_SEQUENCE[BACKOFF_SEQUENCE.length - 1];
    backoffIndex = Math.min(backoffIndex + 1, BACKOFF_SEQUENCE.length - 1);

    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      _openSocket();
    }, delay);
  }

  function sendCommand(commandName, payload, requestId, roomVersion) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;

    var msg = {
      type: "command",
      requestId: requestId || _generateRequestId(),
      roomVersion: roomVersion || 0,
      command: commandName,
      payload: payload || {},
    };

    ws.send(JSON.stringify(msg));
    return true;
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      ws.onclose = null;
      ws.close();
      ws = null;
    }
    identity = null;
    backoffIndex = 0;
  }

  function isConnected() {
    return ws !== null && ws.readyState === WebSocket.OPEN;
  }

  function _generateRequestId() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(
      /[xy]/g,
      function (c) {
        var r = (Math.random() * 16) | 0;
        var v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      }
    );
  }

  return {
    connect: connect,
    sendCommand: sendCommand,
    disconnect: disconnect,
    isConnected: isConnected,
  };
})();
