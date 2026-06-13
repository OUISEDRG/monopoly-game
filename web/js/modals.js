/**
 * modals.js - command modals for property, auction, trade, and debt flows.
 */

"use strict";

var Modals = (function () {
  var root = null;
  var snapshot = null;
  var myPlayerId = null;
  var privateTradeDetail = null;

  function init(modalRoot) {
    root = modalRoot;
  }

  function updateFromSnapshot(nextSnapshot, playerId) {
    snapshot = nextSnapshot;
    myPlayerId = playerId;
    var game = snapshot && snapshot.state ? snapshot.state.game : null;
    if (!game) {
      close();
      return;
    }
    if (game.phase === "awaiting_property_decision" && game.currentPlayerId === myPlayerId) {
      openPropertyDecision(game);
    } else if (game.phase === "auction") {
      openAuction(game);
    } else if (game.phase === "trade_negotiation") {
      openTradeReview(game);
    } else if (game.phase === "debt_relief") {
      openDebt(game);
    } else if (root && root.dataset.auto === "true") {
      close();
    }
  }

  function receivePrivateEvent(event) {
    if (event.type === "trade_offer_detail") {
      privateTradeDetail = event;
      var game = snapshot && snapshot.state ? snapshot.state.game : null;
      if (game && game.phase === "trade_negotiation") openTradeReview(game);
    }
  }

  function openPropertyDecision(game) {
    var pending = game.pendingDecision || {};
    var space = findSpace(pending.position);
    var card = createCard("购买地产");
    appendText(card, (space ? space.name : "该地产") + " 可以购买。");
    appendText(card, "价格 $" + (space ? space.price : 0));
    var actions = appendActions(card);
    actions.appendChild(makeButton("购买", function () { send("BUY_PROPERTY", {}); close(); }));
    actions.appendChild(makeButton("放弃并拍卖", function () { send("DECLINE_PROPERTY", {}); close(); }));
    show(card, true);
  }

  function openAuction(game) {
    var auction = game.auction;
    if (!auction) return;
    var bidder = findCurrentAuctionBidder(auction);
    var isMyBid = bidder && bidder.id === myPlayerId;
    var card = createCard("拍卖");
    var space = findSpace(auction.position);
    appendText(card, (space ? space.name : "地产") + " 当前最高价 $" + auction.highestBid);
    appendText(card, isMyBid ? "轮到你出价或退出。" : "等待其他玩家。");
    var amount = document.createElement("input");
    amount.type = "number";
    amount.min = String((auction.highestBid || 0) + 50);
    amount.step = "50";
    amount.value = String((auction.highestBid || 0) + 50);
    amount.disabled = !isMyBid;
    card.appendChild(amount);
    var actions = appendActions(card);
    actions.appendChild(makeButton("出价", function () {
      send("PLACE_BID", { amount: Number(amount.value) });
      close();
    }, !isMyBid));
    actions.appendChild(makeButton("退出", function () { send("PASS_AUCTION", {}); close(); }, !isMyBid));
    show(card, true);
  }

  function openTrade(nextSnapshot, playerId) {
    snapshot = nextSnapshot || snapshot;
    myPlayerId = playerId || myPlayerId;
    var state = snapshot ? snapshot.state : null;
    if (!state) return;
    var targets = (state.players || []).filter(function (player) {
      return player.id !== myPlayerId && !player.bankrupt;
    });
    var me = findMe();
    var card = createCard("发起交易");
    if (!targets.length || !me) {
      appendText(card, "当前没有可交易对象。");
      show(card, false);
      return;
    }
    var target = document.createElement("select");
    targets.forEach(function (player) {
      var option = document.createElement("option");
      option.value = player.id;
      option.textContent = player.nickname;
      target.appendChild(option);
    });
    card.appendChild(target);
    var grid = document.createElement("div");
    grid.className = "trade-grid";
    var mine = makeAssetPane("你提供", me.properties || []);
    var theirs = makeAssetPane("希望获得", targets[0].properties || []);
    grid.appendChild(mine.wrap);
    grid.appendChild(theirs.wrap);
    card.appendChild(grid);
    target.addEventListener("change", function () {
      var selected = targets.find(function (player) { return player.id === target.value; });
      replaceAssetPane(theirs, selected ? selected.properties || [] : []);
    });
    var actions = appendActions(card);
    actions.appendChild(makeButton("发送", function () {
      send("PROPOSE_TRADE", {
        targetId: target.value,
        initiatorOffer: readOffer(mine),
        targetOffer: readOffer(theirs),
      });
      close();
    }));
    actions.appendChild(makeButton("取消", close));
    show(card, false);
  }

  function openTradeReview(game) {
    if (!game.trade) return;
    var trade = game.trade;
    var isResponder = trade.currentResponder === myPlayerId;
    var card = createCard("交易回应");
    appendText(card, "当前回应者：" + playerName(trade.currentResponder));
    if (privateTradeDetail) {
      appendText(card, "报价详情已收到，仅交易双方可见。");
    } else {
      appendText(card, "等待交易详情。");
    }
    var actions = appendActions(card);
    actions.appendChild(makeButton("接受", function () { send("ACCEPT_TRADE", {}); close(); }, !isResponder));
    actions.appendChild(makeButton("拒绝", function () { send("REJECT_TRADE", {}); close(); }, !isResponder));
    actions.appendChild(makeButton("还价", function () {
      var detail = privateTradeDetail || trade;
      send("COUNTER_TRADE", {
        initiatorOffer: detail.initiatorOffer || { properties: [], cash: 0, jailFreeCard: false },
        targetOffer: detail.targetOffer || { properties: [], cash: 0, jailFreeCard: false },
      });
      close();
    }, !isResponder));
    show(card, true);
  }

  function openDebt(game) {
    var debt = game.debt;
    if (!debt) return;
    var isDebtor = debt.playerId === myPlayerId;
    var card = createCard("债务处置");
    appendText(card, "仍需筹集 $" + debt.owedAmount);
    var me = findMe();
    var properties = me ? me.properties || [] : [];
    var property = document.createElement("select");
    properties.forEach(function (position) {
      var option = document.createElement("option");
      option.value = String(position);
      option.textContent = findSpace(position).name;
      property.appendChild(option);
    });
    card.appendChild(property);
    var actions = appendActions(card);
    actions.appendChild(makeButton("出售建筑", function () {
      send("DEBT_ACTION", { action: "sell_building", position: Number(property.value) });
    }, !isDebtor || !properties.length));
    actions.appendChild(makeButton("抵押地产", function () {
      send("DEBT_ACTION", { action: "mortgage", position: Number(property.value) });
    }, !isDebtor || !properties.length));
    show(card, true);
  }

  function createCard(title) {
    var card = document.createElement("div");
    card.className = "modal-card";
    var heading = document.createElement("h2");
    heading.textContent = title;
    card.appendChild(heading);
    return card;
  }

  function show(card, auto) {
    if (!root) return;
    close();
    var backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.dataset.auto = auto ? "true" : "false";
    backdrop.appendChild(card);
    root.dataset.auto = auto ? "true" : "false";
    root.appendChild(backdrop);
  }

  function close() {
    if (!root) return;
    while (root.firstChild) root.removeChild(root.firstChild);
    root.dataset.auto = "false";
  }

  function appendText(parent, text) {
    var p = document.createElement("p");
    p.textContent = text;
    parent.appendChild(p);
  }

  function appendActions(parent) {
    var actions = document.createElement("div");
    actions.className = "modal-actions";
    parent.appendChild(actions);
    return actions;
  }

  function makeButton(label, handler, disabled) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.disabled = !!disabled;
    button.addEventListener("click", handler);
    return button;
  }

  function makeAssetPane(title, properties) {
    var wrap = document.createElement("section");
    var heading = document.createElement("h2");
    heading.textContent = title;
    var list = document.createElement("div");
    list.className = "asset-list";
    wrap.appendChild(heading);
    wrap.appendChild(list);
    var cash = document.createElement("input");
    cash.type = "number";
    cash.min = "0";
    cash.step = "50";
    cash.value = "0";
    wrap.appendChild(cash);
    var pane = { wrap: wrap, list: list, cash: cash };
    replaceAssetPane(pane, properties);
    return pane;
  }

  function replaceAssetPane(pane, properties) {
    while (pane.list.firstChild) pane.list.removeChild(pane.list.firstChild);
    properties.forEach(function (position) {
      var label = document.createElement("label");
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = String(position);
      var text = document.createElement("span");
      text.textContent = findSpace(position).name;
      label.appendChild(checkbox);
      label.appendChild(text);
      pane.list.appendChild(label);
    });
  }

  function readOffer(pane) {
    var checked = Array.from(pane.list.querySelectorAll("input:checked")).map(function (input) {
      return Number(input.value);
    });
    return {
      properties: checked,
      cash: Math.max(0, Number(pane.cash.value) || 0),
      jailFreeCard: false,
    };
  }

  function send(command, payload) {
    if (window.Actions) window.Actions.sendCommand(command, payload || {});
  }

  function findMe() {
    if (!snapshot) return null;
    return (snapshot.state.players || []).find(function (player) {
      return player.id === myPlayerId;
    }) || null;
  }

  function playerName(playerId) {
    if (!snapshot) return "";
    var player = (snapshot.state.players || []).find(function (item) {
      return item.id === playerId;
    });
    return player ? player.nickname : "";
  }

  function findCurrentAuctionBidder(auction) {
    if (!snapshot) return null;
    return (snapshot.state.players || []).find(function (player) {
      return player.seat === auction.currentBidderSeat;
    }) || null;
  }

  function findSpace(position) {
    var spaces = window.GameRenderer ? window.GameRenderer.getSpaces() : [];
    return spaces[position] || { name: "未知", price: 0 };
  }

  return {
    init: init,
    updateFromSnapshot: updateFromSnapshot,
    receivePrivateEvent: receivePrivateEvent,
    openTrade: openTrade,
    close: close,
  };
})();
