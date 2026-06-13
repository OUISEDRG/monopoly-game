/**
 * lobby.js — 大厅 UI 实时更新
 *
 * 接收快照后更新玩家列表和准备状态。
 * 使用 textContent，禁止 innerHTML。
 */

"use strict";

var Lobby = (function () {
  var playerListEl = null;
  var readyBtnEl = null;
  var startBtnEl = null;
  var statusEl = null;
  var currentSnapshot = null;
  var isReady = false;

  function init(elements) {
    playerListEl = elements.playerList;
    readyBtnEl = elements.readyBtn;
    startBtnEl = elements.startBtn;
    statusEl = elements.status;
  }

  function updateFromSnapshot(snapshot, myPlayerId) {
    currentSnapshot = snapshot;
    var state = snapshot.state;

    // 更新玩家列表
    if (playerListEl) {
      // 清空
      while (playerListEl.firstChild) {
        playerListEl.removeChild(playerListEl.firstChild);
      }

      var players = state.players || [];
      for (var i = 0; i < players.length; i++) {
        var p = players[i];
        var item = document.createElement("div");
        item.className = "player-item";

        var nameSpan = document.createElement("span");
        nameSpan.className = "player-name";
        nameSpan.textContent = p.nickname;

        var statusSpan = document.createElement("span");
        statusSpan.className = "player-status";
        var statusText = "";
        if (!p.connected) {
          statusText = " [断线]";
        } else if (p.ready) {
          statusText = " [准备]";
        }
        statusSpan.textContent = statusText;

        item.appendChild(nameSpan);
        item.appendChild(statusSpan);
        playerListEl.appendChild(item);

        // 记录自己的准备状态
        if (p.id === myPlayerId) {
          isReady = p.ready;
        }
      }
    }

    // 更新准备按钮
    if (readyBtnEl) {
      readyBtnEl.textContent = isReady ? "取消准备" : "准备";
    }

    // 更新开始按钮
    if (startBtnEl) {
      var isHost = state.hostPlayerId === myPlayerId;
      var allReady = (state.players || []).every(function (p) {
        return p.ready;
      });
      var enoughPlayers = (state.players || []).length >= 2;

      startBtnEl.disabled = !(isHost && allReady && enoughPlayers);
      if (!isHost) {
        startBtnEl.textContent = "等待房主开始";
      } else {
        startBtnEl.textContent = "开始游戏";
      }
    }
  }

  function getIsReady() {
    return isReady;
  }

  function getCurrentSnapshot() {
    return currentSnapshot;
  }

  return {
    init: init,
    updateFromSnapshot: updateFromSnapshot,
    getIsReady: getIsReady,
    getCurrentSnapshot: getCurrentSnapshot,
  };
})();
