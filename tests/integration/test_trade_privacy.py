"""交易隐私集成测试。

验收标准：
- 完整报价用 private_events 只发给双方
- 公共快照只含发起者/目标/回应者/还价轮数
- 第三人看不到资产明细
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from server.engine.rules import FixedRandomSource, apply_command
from server.engine.trade import apply_counter_trade, apply_propose_trade
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


def _own_property(game: GameState, player: PlayerState, position: int) -> None:
    game.property_owners[position] = player.id
    if position not in player.properties:
        player.properties.append(position)


def _propose_payload(target_id, **kwargs):
    return {
        "targetId": str(target_id),
        "initiatorOffer": {
            "properties": kwargs.get("initiator_properties", []),
            "cash": kwargs.get("initiator_cash", 0),
            "jailFreeCard": kwargs.get("initiator_jail_free", False),
        },
        "targetOffer": {
            "properties": kwargs.get("target_properties", []),
            "cash": kwargs.get("target_cash", 0),
            "jailFreeCard": kwargs.get("target_jail_free", False),
        },
    }


# ---------------------------------------------------------------------------
# 隐私测试
# ---------------------------------------------------------------------------


class TestTradePrivacy:
    """完整报价只发给交易双方，公共快照不含资产明细。"""

    def test_propose_private_events_only_to_parties(self):
        """发起交易时，完整报价只发给发起者和目标。"""
        players = [_make_player(seat=0), _make_player(seat=1), _make_player(seat=2)]
        game = GameState(
            current_player_id=players[0].id,
            phase=TurnPhase.WAITING_FOR_ROLL,
            trade_window_available=True,
        )
        _own_property(game, players[0], 1)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_payload(
                players[1].id,
                initiator_properties=[1],
                target_cash=500,
            ),
            players=players,
        )

        # private_events 只包含双方
        assert players[0].id in result.private_events
        assert players[1].id in result.private_events
        assert players[2].id not in result.private_events

        # 私密事件包含完整报价
        for pid in [players[0].id, players[1].id]:
            detail_events = [e for e in result.private_events[pid] if e.get("type") == "trade_offer_detail"]
            assert len(detail_events) == 1
            detail = detail_events[0]
            assert "initiatorOffer" in detail
            assert "targetOffer" in detail
            assert detail["initiatorOffer"]["properties"] == [1]
            assert detail["targetOffer"]["cash"] == 500

    def test_propose_public_event_no_asset_details(self):
        """公共事件不含资产明细。"""
        players = [_make_player(seat=0), _make_player(seat=1), _make_player(seat=2)]
        game = GameState(
            current_player_id=players[0].id,
            phase=TurnPhase.WAITING_FOR_ROLL,
            trade_window_available=True,
        )
        _own_property(game, players[0], 1)

        result = apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_payload(
                players[1].id,
                initiator_properties=[1],
                target_cash=500,
            ),
            players=players,
        )

        # 公共事件不含 properties/cash/jailFreeCard
        public_events = [e for e in result.events if e.get("type") == "trade_proposed"]
        assert len(public_events) == 1
        public = public_events[0]
        assert "initiatorOffer" not in public
        assert "targetOffer" not in public
        assert "properties" not in public
        # 公共事件包含元数据
        assert "initiatorId" in public
        assert "targetId" in public
        assert "currentResponder" in public
        assert "counterRounds" in public

    def test_counter_private_events_only_to_parties(self):
        """还价时，完整报价只发给双方。"""
        players = [_make_player(seat=0, money=5000), _make_player(seat=1, money=5000), _make_player(seat=2)]
        game = GameState(
            current_player_id=players[0].id,
            phase=TurnPhase.WAITING_FOR_ROLL,
            trade_window_available=True,
        )
        _own_property(game, players[0], 1)
        _own_property(game, players[1], 3)

        apply_propose_trade(
            game=game, actor_id=players[0].id,
            payload=_propose_payload(
                players[1].id,
                initiator_properties=[1],
                target_properties=[3],
            ),
            players=players,
        )

        result = apply_counter_trade(
            game=game, actor_id=players[1].id,
            payload={
                "initiatorOffer": {"properties": [1], "cash": 200, "jailFreeCard": False},
                "targetOffer": {"properties": [3], "cash": 0, "jailFreeCard": False},
            },
            players=players,
        )

        # private_events 只包含双方
        assert players[0].id in result.private_events
        assert players[1].id in result.private_events
        assert players[2].id not in result.private_events

        # 私密事件包含更新后的报价
        for pid in [players[0].id, players[1].id]:
            detail_events = [e for e in result.private_events[pid] if e.get("type") == "trade_offer_detail"]
            assert len(detail_events) == 1
            assert detail_events[0]["initiatorOffer"]["cash"] == 200

    def test_third_player_sees_no_details(self):
        """第三人通过 apply_command 调用时看不到资产明细。"""
        players = [_make_player(seat=0), _make_player(seat=1), _make_player(seat=2)]
        game = GameState(
            current_player_id=players[0].id,
            phase=TurnPhase.WAITING_FOR_ROLL,
            trade_window_available=True,
        )
        _own_property(game, players[0], 1)

        result = apply_command(
            game=game, actor_id=players[0].id,
            command=CommandName.PROPOSE_TRADE,
            payload=_propose_payload(
                players[1].id,
                initiator_properties=[1],
                target_cash=500,
            ),
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(), players=players,
        )

        # 第三人不在 private_events 中
        assert players[2].id not in result.private_events

        # 公共事件不含资产明细
        for e in result.events:
            assert "initiatorOffer" not in e
            assert "targetOffer" not in e
