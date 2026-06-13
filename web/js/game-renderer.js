/**
 * game-renderer.js - renders server snapshots into the online board.
 */

"use strict";

const ONLINE_SPACES = [
  { position: 0, type: "go", name: "起 点", group: null, price: null, icon: "→" },
  { position: 1, type: "property", name: "郊区小径", group: "brown", price: 600 },
  { position: 2, type: "destiny", name: "命 运", group: null, price: null, icon: "◆" },
  { position: 3, type: "property", name: "田园路", group: "brown", price: 600 },
  { position: 4, type: "tax", name: "所得税", group: null, price: null, icon: "$" },
  { position: 5, type: "property", name: "山谷道", group: "lightBlue", price: 600 },
  { position: 6, type: "property", name: "林间路", group: "lightBlue", price: 600 },
  { position: 7, type: "chance", name: "机 会", group: null, price: null, icon: "?" },
  { position: 8, type: "property", name: "湖畔道", group: "pink", price: 600 },
  { position: 9, type: "property", name: "春风路", group: "pink", price: 600 },
  { position: 10, type: "jail", name: "监狱/探视", group: null, price: null, icon: "J" },
  { position: 11, type: "property", name: "商业一街", group: "orange", price: 1200 },
  { position: 12, type: "destiny", name: "命 运", group: null, price: null, icon: "◆" },
  { position: 13, type: "property", name: "商业二街", group: "orange", price: 1200 },
  { position: 14, type: "property", name: "商业三街", group: "orange", price: 1200 },
  { position: 15, type: "chance", name: "机 会", group: null, price: null, icon: "?" },
  { position: 16, type: "property", name: "锦绣路", group: "red", price: 1200 },
  { position: 17, type: "property", name: "明珠大道", group: "red", price: 1200 },
  { position: 18, type: "destiny", name: "命 运", group: null, price: null, icon: "◆" },
  { position: 19, type: "property", name: "星光道", group: "red", price: 1200 },
  { position: 20, type: "freeParking", name: "免费停车", group: null, price: null, icon: "P" },
  { position: 21, type: "property", name: "中央一街", group: "yellow", price: 2500 },
  { position: 22, type: "chance", name: "机 会", group: null, price: null, icon: "?" },
  { position: 23, type: "property", name: "中央二街", group: "yellow", price: 2500 },
  { position: 24, type: "property", name: "中央广场", group: "yellow", price: 2500 },
  { position: 25, type: "destiny", name: "命 运", group: null, price: null, icon: "◆" },
  { position: 26, type: "property", name: "金融大道", group: "green", price: 2500 },
  { position: 27, type: "property", name: "世纪路", group: "green", price: 2500 },
  { position: 28, type: "chance", name: "机 会", group: null, price: null, icon: "?" },
  { position: 29, type: "property", name: "国际中心", group: "green", price: 2500 },
  { position: 30, type: "goToJail", name: "前往监狱", group: null, price: null, icon: "锁" },
  { position: 31, type: "property", name: "黄金海岸", group: "darkBlue", price: 4000 },
  { position: 32, type: "property", name: "钻石路", group: "darkBlue", price: 4000 },
  { position: 33, type: "destiny", name: "命 运", group: null, price: null, icon: "◆" },
  { position: 34, type: "property", name: "帝王台", group: "gold", price: 4000 },
  { position: 35, type: "chance", name: "机 会", group: null, price: null, icon: "?" },
  { position: 36, type: "property", name: "至尊道", group: "gold", price: 4000 },
  { position: 37, type: "destiny", name: "命 运", group: null, price: null, icon: "◆" },
  { position: 38, type: "tax", name: "豪宅税", group: null, price: null, icon: "$" },
  { position: 39, type: "destiny", name: "命 运", group: null, price: null, icon: "◆" },
];

var GameRenderer = (function () {
  var elements = {};
  var currentSnapshot = null;
  var myPlayerId = null;
  var colorMap = {
    brown: "#8b4513",
    lightBlue: "#61b5d8",
    pink: "#d84b92",
    orange: "#d87928",
    red: "#d64b3f",
    yellow: "#d9ba24",
    green: "#2f8f55",
    darkBlue: "#233e8b",
    gold: "#c7a33d",
  };

  function init(options) {
    elements = options || {};
    renderBoard();
  }

  function setIdentity(playerId) {
    myPlayerId = playerId;
  }

  function renderSnapshot(snapshot) {
    currentSnapshot = snapshot;
    renderBoard();
    renderPlayers();
    renderProperties();
    renderLog();
    updateActionState();
  }

  function renderBoard() {
    var board = elements.board;
    if (!board) return;
    clear(board);

    var state = currentSnapshot ? currentSnapshot.state : null;
    var players = state ? state.players || [] : [];
    var game = state ? state.game : null;

    for (var i = 0; i < ONLINE_SPACES.length; i++) {
      var space = ONLINE_SPACES[i];
      var cell = document.createElement("div");
      cell.className = "online-cell";
      cell.style.gridColumn = getGridColumn(space.position);
      cell.style.gridRow = getGridRow(space.position);
      cell.dataset.position = String(space.position);

      var color = document.createElement("div");
      color.className = "cell-color";
      color.style.background = colorMap[space.group] || "#d7c7a2";
      cell.appendChild(color);

      var name = document.createElement("div");
      name.className = "cell-name";
      name.textContent = space.name;
      cell.appendChild(name);

      var price = document.createElement("div");
      price.className = "cell-price";
      price.textContent = space.price ? "$" + space.price : space.icon || "";
      cell.appendChild(price);

      var tokenRow = document.createElement("div");
      tokenRow.className = "token-row";
      players.filter(function (player) {
        return player.position === space.position && !player.bankrupt;
      }).forEach(function (player) {
        tokenRow.appendChild(makeToken(player));
      });
      cell.appendChild(tokenRow);
      board.appendChild(cell);
    }

    var center = document.createElement("div");
    center.className = "online-cell center";
    var title = document.createElement("strong");
    title.textContent = game ? phaseLabel(game.phase) : "等待开局";
    var sub = document.createElement("div");
    sub.className = "meta-line";
    sub.textContent = game ? currentTurnText(game, players) : "准备后由房主开始";
    center.appendChild(title);
    center.appendChild(sub);
    board.appendChild(center);
  }

  function renderPlayers() {
    var list = elements.playerList;
    if (!list || !currentSnapshot) return;
    clear(list);
    var state = currentSnapshot.state;
    var game = state.game;
    (state.players || []).forEach(function (player) {
      var card = document.createElement("div");
      card.className = "online-player-card";
      if (game && game.currentPlayerId === player.id) card.className += " current";
      if (player.id === myPlayerId) card.className += " mine";
      if (player.bankrupt) card.className += " bankrupt";
      var name = document.createElement("strong");
      name.textContent = player.nickname;
      var meta = document.createElement("div");
      meta.className = "meta-line";
      meta.textContent = "$" + player.money + " | " + player.properties.length + " 处地产" + (player.connected ? "" : " | 断线");
      card.appendChild(name);
      card.appendChild(meta);
      list.appendChild(card);
    });
  }

  function renderProperties() {
    var list = elements.propertyList;
    if (!list || !currentSnapshot) return;
    clear(list);
    var state = currentSnapshot.state;
    var game = state.game || {};
    var me = findMe();
    if (!me || !me.properties.length) {
      var empty = document.createElement("div");
      empty.className = "online-property-card";
      empty.textContent = "暂无地产";
      list.appendChild(empty);
      return;
    }
    me.properties.forEach(function (position) {
      var space = ONLINE_SPACES[position];
      var item = document.createElement("button");
      item.type = "button";
      item.className = "online-property-card";
      item.dataset.position = String(position);
      item.textContent = space.name + (game.mortgageStatus && game.mortgageStatus[position] ? "（已抵押）" : "");
      item.addEventListener("click", function () {
        if (window.Actions) window.Actions.selectProperty(position);
      });
      list.appendChild(item);
    });
  }

  function renderLog() {
    var log = elements.eventLog;
    if (!log || !currentSnapshot) return;
    clear(log);
    var logs = (currentSnapshot.state.game && currentSnapshot.state.game.logs) || [];
    if (!logs.length) {
      var row = document.createElement("div");
      row.className = "event-row";
      row.textContent = "等待事件";
      log.appendChild(row);
      return;
    }
    logs.slice(-12).forEach(function (entry) {
      var row = document.createElement("div");
      row.className = "event-row";
      row.textContent = entry.message || entry.type || JSON.stringify(entry);
      log.appendChild(row);
    });
  }

  function updateActionState() {
    if (!window.Actions || !currentSnapshot) return;
    window.Actions.updateFromSnapshot(currentSnapshot, myPlayerId);
  }

  function findMe() {
    if (!currentSnapshot) return null;
    return (currentSnapshot.state.players || []).find(function (player) {
      return player.id === myPlayerId;
    }) || null;
  }

  function makeToken(player) {
    var token = document.createElement("span");
    token.className = "player-token";
    token.title = player.nickname;
    token.style.background = player.color || "#333";
    return token;
  }

  function currentTurnText(game, players) {
    var current = players.find(function (player) {
      return player.id === game.currentPlayerId;
    });
    var text = current ? "当前：" + current.nickname : "当前玩家未知";
    if (game.turnDeadline) text += " | 截止 " + formatTime(game.turnDeadline);
    return text;
  }

  function phaseLabel(phase) {
    var labels = {
      waiting_for_roll: "等待掷骰",
      awaiting_property_decision: "地产决策",
      awaiting_card_decision: "卡牌决策",
      auction: "拍卖中",
      trade_negotiation: "交易中",
      debt_relief: "债务处置",
      game_over: "游戏结束",
    };
    return labels[phase] || phase || "游戏中";
  }

  function formatTime(iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function getGridColumn(position) {
    if (position <= 10) return String(11 - position);
    if (position <= 20) return "1";
    if (position <= 30) return String(position - 19);
    return "11";
  }

  function getGridRow(position) {
    if (position <= 10) return "11";
    if (position <= 20) return String(21 - position);
    if (position <= 30) return "1";
    return String(position - 29);
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  return {
    init: init,
    setIdentity: setIdentity,
    renderSnapshot: renderSnapshot,
    renderBoard: renderBoard,
    getSnapshot: function () { return currentSnapshot; },
    getSpaces: function () { return ONLINE_SPACES.slice(); },
  };
})();
