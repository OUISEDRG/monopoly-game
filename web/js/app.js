/**
 * app.js — 大厅 UI 交互
 *
 * 所有用户文本使用 textContent，禁止 innerHTML 注入。
 * 令牌不出现在 DOM、控制台或错误文本。
 */

"use strict";

(function () {
  var createNickname = document.getElementById("create-nickname");
  var createBtn = document.getElementById("create-btn");
  var joinNickname = document.getElementById("join-nickname");
  var roomCode = document.getElementById("room-code");
  var joinBtn = document.getElementById("join-btn");
  var statusArea = document.getElementById("status");
  var errorArea = document.getElementById("error");
  var entrySection = document.getElementById("entry-section");
  var roomSection = document.getElementById("room-section");
  var gameSection = document.getElementById("game-section");
  var roomTitle = document.getElementById("room-title");
  var roomChip = document.getElementById("room-chip");
  var connectionLabel = document.getElementById("connection-label");
  var readyBtn = document.getElementById("ready-btn");
  var startBtn = document.getElementById("start-btn");
  var leaveBtn = document.getElementById("leave-btn");

  var currentIdentity = null;
  var currentRoomVersion = 0;

  function clearMessages() {
    statusArea.textContent = "";
    errorArea.textContent = "";
  }

  function showStatus(msg) {
    statusArea.textContent = msg;
  }

  function showError(msg) {
    errorArea.textContent = msg;
  }

  function setEntryButtonsDisabled(disabled) {
    createBtn.disabled = disabled;
    joinBtn.disabled = disabled;
  }

  function showRoomSection() {
    entrySection.style.display = "none";
    roomSection.style.display = "";
    gameSection.style.display = "none";
  }

  function showEntrySection() {
    entrySection.style.display = "";
    roomSection.style.display = "none";
    gameSection.style.display = "none";
  }

  function showGameSection() {
    entrySection.style.display = "none";
    roomSection.style.display = "none";
    gameSection.style.display = "";
  }

  async function apiPost(url, body) {
    var resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    var data = await resp.json();
    if (!resp.ok) {
      throw { status: resp.status, data: data };
    }
    return data;
  }

  function connectWebSocket(identity) {
    currentIdentity = identity;

    Lobby.init({
      playerList: document.getElementById("player-list"),
      readyBtn: readyBtn,
      startBtn: startBtn,
      status: statusArea,
    });
    GameRenderer.init({
      board: document.getElementById("online-board"),
      playerList: document.getElementById("online-player-list"),
      propertyList: document.getElementById("online-property-list"),
      eventLog: document.getElementById("online-event-log"),
    });
    GameRenderer.setIdentity(identity.playerId);
    Actions.init({
      roll: document.getElementById("online-roll-btn"),
      buy: document.getElementById("online-buy-btn"),
      decline: document.getElementById("online-decline-btn"),
      trade: document.getElementById("online-trade-btn"),
      build: document.getElementById("online-build-btn"),
      mortgage: document.getElementById("online-mortgage-btn"),
      unmortgage: document.getElementById("online-unmortgage-btn"),
    });
    Modals.init(document.getElementById("online-modal-root"));

    Network.connect(identity, {
      onSnapshot: function (snapshot) {
        currentRoomVersion = snapshot.roomVersion;
        roomChip.textContent = snapshot.state.code;
        Lobby.updateFromSnapshot(snapshot, identity.playerId);
        if (snapshot.state.phase === "playing") {
          showGameSection();
          GameRenderer.renderSnapshot(snapshot);
        } else {
          showRoomSection();
        }
      },
      onCommandResult: function (result) {
        if (!result.accepted && result.error) {
          showError(result.error.message || "操作失败");
        }
      },
      onConnectionChange: function (connected) {
        if (connected) {
          connectionLabel.textContent = "已连接";
          showStatus("已连接");
        } else {
          connectionLabel.textContent = "正在重连";
          showStatus("正在重连...");
        }
      },
      onPrivateEvent: function (event) {
        Modals.receivePrivateEvent(event);
      },
    });
  }

  async function handleCreate() {
    clearMessages();
    var nickname = createNickname.value.trim();
    if (!nickname || nickname.length > 12) {
      showError("昵称长度必须为 1-12 个字符");
      return;
    }
    setEntryButtonsDisabled(true);
    try {
      var data = await apiPost("/api/rooms", { nickname: nickname });
      var identity = {
        roomCode: data.roomCode,
        playerId: data.playerId,
        reconnectToken: data.reconnectToken,
        websocketPath: data.websocketPath,
      };
      saveIdentity(identity);
      currentIdentity = identity;
      roomTitle.textContent = "房间 " + data.roomCode;
      roomChip.textContent = data.roomCode;
      showRoomSection();
      connectWebSocket(identity);
    } catch (err) {
      var msg =
        err.data && err.data.message
          ? err.data.message
          : "创建房间失败，请重试";
      showError(msg);
    } finally {
      setEntryButtonsDisabled(false);
    }
  }

  async function handleJoin() {
    clearMessages();
    var nickname = joinNickname.value.trim();
    var code = roomCode.value.trim().toUpperCase();
    if (!nickname || nickname.length > 12) {
      showError("昵称长度必须为 1-12 个字符");
      return;
    }
    if (code.length !== 6) {
      showError("房间码必须为 6 位");
      return;
    }
    setEntryButtonsDisabled(true);
    try {
      var data = await apiPost("/api/rooms/" + code + "/join", {
        nickname: nickname,
      });
      var identity = {
        roomCode: data.roomCode,
        playerId: data.playerId,
        reconnectToken: data.reconnectToken,
        websocketPath: data.websocketPath,
      };
      saveIdentity(identity);
      currentIdentity = identity;
      roomTitle.textContent = "房间 " + data.roomCode;
      roomChip.textContent = data.roomCode;
      showRoomSection();
      connectWebSocket(identity);
    } catch (err) {
      var msg =
        err.data && err.data.message
          ? err.data.message
          : "加入房间失败，请重试";
      showError(msg);
    } finally {
      setEntryButtonsDisabled(false);
    }
  }

  function handleReady() {
    var newReady = !Lobby.getIsReady();
    Network.sendCommand("SET_READY", { ready: newReady }, null, currentRoomVersion);
  }

  function handleStart() {
    Network.sendCommand("START_GAME", {}, null, currentRoomVersion);
  }

  function handleLeave() {
    Network.sendCommand("LEAVE_ROOM", {}, null, currentRoomVersion);
    Network.disconnect();
    clearIdentity();
    currentIdentity = null;
    roomChip.textContent = "大厅";
    connectionLabel.textContent = "未连接";
    showEntrySection();
    clearMessages();
  }

  createBtn.addEventListener("click", handleCreate);
  joinBtn.addEventListener("click", handleJoin);
  readyBtn.addEventListener("click", handleReady);
  startBtn.addEventListener("click", handleStart);
  leaveBtn.addEventListener("click", handleLeave);

  // 检查已有身份，自动重连
  var existing = loadIdentity();
  if (existing) {
    roomTitle.textContent = "房间 " + existing.roomCode;
    roomChip.textContent = existing.roomCode;
    showRoomSection();
    connectWebSocket(existing);
  }
})();
