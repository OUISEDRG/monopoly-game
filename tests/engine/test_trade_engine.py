"""完整玩家交易系统测试。

覆盖验收标准：
- PROPOSE_TRADE：WAITING_FOR_ROLL + 当前玩家，多地产 + 非负现金 + 出狱卡
- ACCEPT_TRADE：目标玩家 + TRADE_NEGOTIATION 阶段；交割前校验；原子转移
- REJECT_TRADE：拒绝并关闭本回合交易窗口
- COUNTER_TRADE：还价刷新资产，最多两轮
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from server.engine.board import COLOR_GROUPS
from server.engine.commands import EngineResult
from server.engine.rules import FixedRandomSource, apply_command
from server.engine.trade import (
    MAX_COUNTER_ROUNDS,
    TradeOffer,
    TradeState,
    apply_accept_trade,
    apply_counter_trade,
    apply_propose_trade,
    apply_reject_trade,
)
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState
from server.protocol import CommandName


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_player(*, seat: int = 0, money: int = 15000) -> PlayerState:
    return PlayerState(
        id=uuid4(),
        nickname=f"p{seat}",
        seat=seat,
        color=f"color{seat}",
        money=money,
    )


def _make_game(players: list[PlayerState] | None = None) -> GameState:
    if players is None:
        players = [_make_player(seat=0), _make_player(seat=1), _make_player(seat=2)]
    return GameState(
        current_player_id=players[0].id,
        phase=TurnPhase.WAITING_FOR_ROLL,
        trade_window_available=True,
    )


def _own_property(game: GameState, player: PlayerState, position: int) -> None:
    game.property_owners[position] = player.id
    if position not in player.properties:
        player.properties.append(position)


def _propose_trade_payload(
    target_id,
    initiator_properties=None,
    initiator_cash=0,
    initiator_jail_free=False,
    target_properties=None,
    target_cash=0,
    target_jail_free=False,
):
    return {
        "targetId": str(target_id),
        "initiatorOffer": {
            "properties": initiator_properties or [],
            "cash": initiator_cash,
            "jailFreeCard": initiator_jail_free,
        },
        "targetOffer": {
            "properties": target_properties or [],
            "cash": target_cash,
            "jailFreeCard": target_jail_free,
        },
    }


# ---------------------------------------------------------------------------
# PROPOSE_TRADE 测试
# ---------------------------------------------------------------------------


class TestProposeTradePhaseAndPlayer:
    """PROPOSE_TRADE 仅 WAITING_FOR_ROLL + 当前玩家。"""

    def test_wrong_phase_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AUCTION

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_cash=100),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)

    def test_not_current_player_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_propose_trade(
            game=game, actor_id=players[1].id,
            payload=_propose_trade_payload(players[0].id, initiator_cash=100),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_CURRENT_PLAYER" for e in result.events)


class TestProposeTradeWindow:
    """每回合最多一笔交易。"""

    def test_trade_window_closed_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        game.trade_window_available = False

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_cash=100),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "TRADE_WINDOW_CLOSED" for e in result.events)

    def test_trade_already_in_progress_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        game.trade = TradeState(
            initiator_id=players[0].id,
            target_id=players[1].id,
            initiator_offer=TradeOffer(cash=100),
            target_offer=TradeOffer(),
        )

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_cash=200),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "TRADE_IN_PROGRESS" for e in result.events)


class TestProposeTradeTarget:
    """目标玩家校验。"""

    def test_self_trade_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[0].id, initiator_cash=100),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_TARGET" for e in result.events)

    def test_bankrupt_target_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        players[1].bankrupt = True
        game = _make_game(players)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_cash=100),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_TARGET" for e in result.events)


class TestProposeTradeAssetValidation:
    """资产校验：地产所有权、建筑限制、现金、出狱卡。"""

    def test_property_not_owned_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        # 位置 1 不属于玩家 0
        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_properties=[1]),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)

    def test_property_with_buildings_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        _own_property(game, players[0], 1)
        game.building_levels[1] = 2

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_properties=[1]),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)

    def test_insufficient_cash_rejected(self):
        players = [_make_player(seat=0, money=100), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_cash=500),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)

    def test_negative_cash_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_cash=-100),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)

    def test_jail_free_card_not_owned_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_jail_free=True),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)

    def test_empty_trade_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)

    def test_duplicate_properties_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        _own_property(game, players[0], 1)
        _own_property(game, players[1], 1)  # 同一地产出现在双方

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(
                players[1].id,
                initiator_properties=[1],
                target_properties=[1],
            ),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)

    def test_valid_trade_succeeds(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        _own_property(game, players[0], 1)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_properties=[1]),
            players=players,
        )
        assert result.changed is True
        assert game.phase == TurnPhase.TRADE_NEGOTIATION
        assert game.trade is not None
        assert game.trade.current_responder == players[1].id


# ---------------------------------------------------------------------------
# ACCEPT_TRADE 测试
# ---------------------------------------------------------------------------


class TestAcceptTrade:
    """ACCEPT_TRADE：目标玩家 + TRADE_NEGOTIATION 阶段；原子转移。"""

    def _setup_trade(self):
        players = [_make_player(seat=0, money=5000), _make_player(seat=1, money=5000)]
        game = _make_game(players)
        _own_property(game, players[0], 1)
        apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_properties=[1], target_cash=500),
            players=players,
        )
        return game, players

    def test_wrong_phase_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.WAITING_FOR_ROLL

        result = apply_accept_trade(
            game=game, actor_id=players[1].id,
            payload={}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)

    def test_not_responder_rejected(self):
        game, players = self._setup_trade()
        # 发起者不能接受
        result = apply_accept_trade(
            game=game, actor_id=players[0].id,
            payload={}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_RESPONDER" for e in result.events)

    def test_accept_transfers_assets(self):
        game, players = self._setup_trade()
        assert game.property_owners[1] == players[0].id

        result = apply_accept_trade(
            game=game, actor_id=players[1].id,
            payload={}, players=players,
        )
        assert result.changed is True
        # 地产转移
        assert game.property_owners[1] == players[1].id
        assert 1 in players[1].properties
        assert 1 not in players[0].properties
        # 现金转移
        assert players[0].money == 5000 + 500  # 收到 500
        assert players[1].money == 5000 - 500  # 支付 500
        # 状态恢复
        assert game.phase == TurnPhase.WAITING_FOR_ROLL
        assert game.trade is None
        assert game.trade_window_available is False

    def test_accept_with_jail_free_card(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        players[0].has_get_out_of_jail_card = True
        _own_property(game, players[1], 3)

        apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_jail_free=True, target_properties=[3]),
            players=players,
        )
        result = apply_accept_trade(
            game=game, actor_id=players[1].id,
            payload={}, players=players,
        )
        assert result.changed is True
        assert players[0].has_get_out_of_jail_card is False
        assert players[1].has_get_out_of_jail_card is True
        assert game.property_owners[3] == players[0].id

    def test_accept_assets_changed_cancels(self):
        """交割前资产变更导致交易取消。"""
        game, players = self._setup_trade()
        # 模拟目标玩家现金减少
        players[1].money = 100  # 不够支付 500

        result = apply_accept_trade(
            game=game, actor_id=players[1].id,
            payload={}, players=players,
        )
        # 交易取消（资产校验失败）
        assert result.changed is True
        assert any(e.get("type") == "trade_cancelled" for e in result.events)
        # 地产不转移
        assert game.property_owners[1] == players[0].id


# ---------------------------------------------------------------------------
# REJECT_TRADE 测试
# ---------------------------------------------------------------------------


class TestRejectTrade:
    """REJECT_TRADE：拒绝并关闭本回合交易窗口。"""

    def _setup_trade(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        _own_property(game, players[0], 1)
        apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_properties=[1]),
            players=players,
        )
        return game, players

    def test_reject_closes_trade(self):
        game, players = self._setup_trade()

        result = apply_reject_trade(
            game=game, actor_id=players[1].id,
            payload={}, players=players,
        )
        assert result.changed is True
        assert game.phase == TurnPhase.WAITING_FOR_ROLL
        assert game.trade is None
        assert game.trade_window_available is False
        # 地产不转移
        assert game.property_owners[1] == players[0].id

    def test_not_responder_rejected(self):
        game, players = self._setup_trade()

        result = apply_reject_trade(
            game=game, actor_id=players[0].id,
            payload={}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_RESPONDER" for e in result.events)

    def test_cannot_trade_again_after_reject(self):
        game, players = self._setup_trade()
        apply_reject_trade(
            game=game, actor_id=players[1].id,
            payload={}, players=players,
        )

        # 尝试再次发起交易
        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_cash=100),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "TRADE_WINDOW_CLOSED" for e in result.events)


# ---------------------------------------------------------------------------
# COUNTER_TRADE 测试
# ---------------------------------------------------------------------------


class TestCounterTrade:
    """COUNTER_TRADE：还价刷新资产，最多两轮。"""

    def _setup_trade(self):
        players = [_make_player(seat=0, money=5000), _make_player(seat=1, money=5000)]
        game = _make_game(players)
        _own_property(game, players[0], 1)
        _own_property(game, players[1], 3)
        apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_trade_payload(players[1].id, initiator_properties=[1], target_properties=[3]),
            players=players,
        )
        return game, players

    def test_counter_updates_offer(self):
        game, players = self._setup_trade()

        result = apply_counter_trade(
            game=game, actor_id=players[1].id,
            payload={
                "initiatorOffer": {"properties": [1], "cash": 200, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )
        assert result.changed is True
        assert game.trade.initiator_offer.cash == 200
        assert game.trade.counter_rounds == 1
        # 回应者切换到发起者
        assert game.trade.current_responder == players[0].id

    def test_max_counter_rounds_rejected(self):
        game, players = self._setup_trade()
        game.trade.counter_rounds = MAX_COUNTER_ROUNDS

        result = apply_counter_trade(
            game=game, actor_id=players[1].id,
            payload={
                "initiatorOffer": {"properties": [1], "cash": 200, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "MAX_COUNTER_ROUNDS" for e in result.events)

    def test_two_rounds_counter(self):
        """两轮还价流程。"""
        game, players = self._setup_trade()

        # 第 1 轮：目标还价
        apply_counter_trade(
            game=game, actor_id=players[1].id,
            payload={
                "initiatorOffer": {"properties": [1], "cash": 200, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )
        assert game.trade.counter_rounds == 1
        assert game.trade.current_responder == players[0].id

        # 第 2 轮：发起者还价
        apply_counter_trade(
            game=game, actor_id=players[0].id,
            payload={
                "initiatorOffer": {"properties": [1], "cash": 300, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )
        assert game.trade.counter_rounds == 2
        assert game.trade.current_responder == players[1].id

        # 第 3 轮被拒绝
        result = apply_counter_trade(
            game=game, actor_id=players[1].id,
            payload={
                "initiatorOffer": {"properties": [1], "cash": 400, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "MAX_COUNTER_ROUNDS" for e in result.events)

    def test_counter_then_accept(self):
        """还价后接受。"""
        game, players = self._setup_trade()

        # 目标还价：发起者出地产1+200现金，目标出地产3
        apply_counter_trade(
            game=game, actor_id=players[1].id,
            payload={
                "initiatorOffer": {"properties": [1], "cash": 200, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )

        # 发起者接受
        result = apply_accept_trade(
            game=game, actor_id=players[0].id,
            payload={}, players=players,
        )
        assert result.changed is True
        assert game.property_owners[1] == players[1].id
        assert game.property_owners[3] == players[0].id
        # 发起者支付 200，收到 0
        assert players[0].money == 5000 - 200
        # 目标收到 200，支付 0
        assert players[1].money == 5000 + 200

    def test_counter_invalid_offer_rejected(self):
        game, players = self._setup_trade()

        result = apply_counter_trade(
            game=game, actor_id=players[1].id,
            payload={
                "initiatorOffer": {"properties": [999], "cash": 0, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_OFFER" for e in result.events)


# ---------------------------------------------------------------------------
# 通过 apply_command 集成测试
# ---------------------------------------------------------------------------


class TestTradeViaApplyCommand:
    """通过 apply_command 调用交易命令。"""

    def test_full_trade_flow_via_apply_command(self):
        players = [_make_player(seat=0, money=5000), _make_player(seat=1, money=5000)]
        game = _make_game(players)
        _own_property(game, players[0], 1)

        # 发起交易
        result = apply_command(
            game=game, actor_id=players[0].id,
            command=CommandName.PROPOSE_TRADE,
            payload=_propose_trade_payload(players[1].id, initiator_properties=[1], target_cash=500),
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(), players=players,
        )
        assert result.changed is True

        # 接受交易
        result = apply_command(
            game=game, actor_id=players[1].id,
            command=CommandName.ACCEPT_TRADE,
            payload={},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.property_owners[1] == players[1].id
