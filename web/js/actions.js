/**
 * actions.js - maps UI controls to server command intents.
 */

"use strict";

var Actions = (function () {
  var snapshot = null;
  var myPlayerId = null;
  var selectedProperty = null;
  var buttons = {};

  function init(elements) {
    buttons = elements || {};
    bind(buttons.roll, function () { sendCommand("ROLL_DICE", {}); });
    bind(buttons.buy, function () { sendCommand("BUY_PROPERTY", {}); });
    bind(buttons.decline, function () { sendCommand("DECLINE_PROPERTY", {}); });
    bind(buttons.trade, function () {
      if (window.Modals) window.Modals.openTrade(snapshot, myPlayerId);
    });
    bind(buttons.build, function () {
      if (selectedProperty !== null) sendCommand("BUILD", { position: selectedProperty });
    });
    bind(buttons.mortgage, function () {
      if (selectedProperty !== null) sendCommand("MORTGAGE", { position: selectedProperty });
    });
    bind(buttons.unmortgage, function () {
      if (selectedProperty !== null) sendCommand("UNMORTGAGE", { position: selectedProperty });
    });
  }

  function updateFromSnapshot(nextSnapshot, playerId) {
    snapshot = nextSnapshot;
    myPlayerId = playerId;
    var game = snapshot && snapshot.state ? snapshot.state.game : null;
    var myTurn = game && game.currentPlayerId === myPlayerId;
    var phase = game ? game.phase : "";
    setDisabled(buttons.roll, !(myTurn && phase === "waiting_for_roll"));
    setDisabled(buttons.buy, !(myTurn && phase === "awaiting_property_decision"));
    setDisabled(buttons.decline, !(myTurn && phase === "awaiting_property_decision"));
    setDisabled(buttons.trade, !(myTurn && phase === "waiting_for_roll" && game.tradeWindowAvailable));
    setDisabled(buttons.build, !(myTurn && phase === "waiting_for_roll" && selectedProperty !== null));
    setDisabled(buttons.mortgage, !(myTurn && phase === "waiting_for_roll" && selectedProperty !== null));
    setDisabled(buttons.unmortgage, !(myTurn && phase === "waiting_for_roll" && selectedProperty !== null));
    if (window.Modals) window.Modals.updateFromSnapshot(snapshot, myPlayerId);
  }

  function selectProperty(position) {
    selectedProperty = position;
    updateFromSnapshot(snapshot, myPlayerId);
  }

  function sendCommand(commandName, payload) {
    if (!snapshot) return false;
    return Network.sendCommand(commandName, payload || {}, null, snapshot.roomVersion);
  }

  function bind(button, handler) {
    if (button) button.addEventListener("click", handler);
  }

  function setDisabled(button, disabled) {
    if (button) button.disabled = !!disabled;
  }

  return {
    init: init,
    updateFromSnapshot: updateFromSnapshot,
    selectProperty: selectProperty,
    sendCommand: sendCommand,
  };
})();
