"""卡牌数据驱动测试。

覆盖 Task 8 验收标准：
- 卡牌数据驱动（稳定 ID，不存 lambda）
- pending_decision 挂起等待客户端
- 至少 5 张典型卡牌测试
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from server.engine.cards import CHANCE_CARDS, DESTINY_CARDS, CardActionType, draw_card, execute_card
from server.engine.commands import EngineResult
from server.engine.rules import FixedRandomSource, apply_command
from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState
from server.protocol import CommandName


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_player(*, seat: int = 0, money: int = 15000, position: int = 0) -> PlayerState:
    return PlayerState(
        id=uuid4(),
        nickname=f"p{seat}",
        seat=seat,
        color=f"color{seat}",
        money=money,
        position=position,
    )


def _make_game(players: list[PlayerState] | None = None) -> GameState:
    if players is None:
        players = [_make_player(seat=0), _make_player(seat=1)]
    return GameState(
        current_player_id=players[0].id,
        phase=TurnPhase.WAITING_FOR_ROLL,
    )


# ---------------------------------------------------------------------------
# 测试：卡牌数据结构
# ---------------------------------------------------------------------------


class TestCardDataStructure:
    def test_chance_cards_have_stable_ids(self):
        """每张机会卡都有稳定 ID。"""
        ids = [c["id"] for c in CHANCE_CARDS]
        assert len(ids) == len(set(ids)), "IDs must be unique"
        assert all(isinstance(i, str) and len(i) > 0 for i in ids)

    def test_destiny_cards_have_stable_ids(self):
        """每张命运卡都有稳定 ID。"""
        ids = [c["id"] for c in DESTINY_CARDS]
        assert len(ids) == len(set(ids)), "IDs must be unique"
        assert all(isinstance(i, str) and len(i) > 0 for i in ids)

    def test_cards_have_action_type_not_lambda(self):
        """卡牌使用 action_type 枚举，不存 lambda。"""
        for card in CHANCE_CARDS + DESTINY_CARDS:
            assert "action_type" in card
            assert isinstance(card["action_type"], str)
            # 不应有 action 函数
            assert "action" not in card or not callable(card.get("action"))

    def test_chance_card_count(self):
        """机会卡数量与旧版一致（12 张）。"""
        assert len(CHANCE_CARDS) == 12

    def test_destiny_card_count(self):
        """命运卡数量与旧版一致（12 张）。"""
        assert len(DESTINY_CARDS) == 12


# ---------------------------------------------------------------------------
# 测试：典型卡牌执行
# ---------------------------------------------------------------------------


class TestCardExecution:
    def test_gain_money_card(self):
        """获得金钱卡：银行红利 +$500。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        card = next(c for c in CHANCE_CARDS if c["id"] == "chance_bank_dividend")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert players[0].money == 15500

    def test_lose_money_card(self):
        """失去金钱卡：汽车维修 -$300。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        card = next(c for c in CHANCE_CARDS if c["id"] == "chance_car_repair")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert players[0].money == 14700

    def test_get_out_of_jail_card(self):
        """出狱免费卡。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        card = next(c for c in CHANCE_CARDS if c["id"] == "chance_jail_free")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert players[0].has_get_out_of_jail_card is True

    def test_go_to_jail_card(self):
        """前往监狱卡。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        card = next(c for c in CHANCE_CARDS if c["id"] == "chance_go_to_jail")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert players[0].in_jail is True
        assert players[0].position == 10

    def test_move_to_go_card(self):
        """前进到起点卡。"""
        players = [_make_player(seat=0, money=15000, position=15), _make_player(seat=1)]
        game = _make_game(players)
        card = next(c for c in CHANCE_CARDS if c["id"] == "chance_advance_to_go")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert players[0].position == 0
        assert players[0].money == 16000  # 15000 + 1000

    def test_move_backwards_card(self):
        """后退卡。"""
        players = [_make_player(seat=0, money=15000, position=10), _make_player(seat=1)]
        game = _make_game(players)
        card = next(c for c in CHANCE_CARDS if c["id"] == "chance_move_back_3")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert players[0].position == 7

    def test_birthday_card(self):
        """生日卡：每位其他玩家给你 $100。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        card = next(c for c in CHANCE_CARDS if c["id"] == "chance_birthday")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert players[0].money == 15100  # +100
        assert players[1].money == 14900  # -100


# ---------------------------------------------------------------------------
# 测试：任意传送卡挂起决策
# ---------------------------------------------------------------------------


class TestTeleportCardDecision:
    def test_teleport_card_sets_pending_decision(self):
        """任意传送卡设置 pending_decision 等待客户端选择。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        card = next(c for c in DESTINY_CARDS if c["id"] == "destiny_teleport")
        result = execute_card(game, players, players[0], card, d1=3, d2=4)
        assert game.pending_decision is not None
        assert game.pending_decision["type"] == "teleport_decision"
        assert game.phase == TurnPhase.AWAITING_CARD_DECISION


# ---------------------------------------------------------------------------
# 测试：draw_card 函数
# ---------------------------------------------------------------------------


class TestDrawCard:
    def test_draw_chance_card(self):
        """从机会卡组抽卡。"""
        random = FixedRandomSource(rolls=[1, 2, 3])  # 第三个值用于卡牌索引
        card = draw_card("chance", random)
        assert card is not None
        assert "id" in card
        assert "text" in card

    def test_draw_destiny_card(self):
        """从命运卡组抽卡。"""
        random = FixedRandomSource(rolls=[1, 2, 5])
        card = draw_card("destiny", random)
        assert card is not None
        assert "id" in card

    def test_draw_deterministic_with_fixed_random(self):
        """固定随机源产生确定性卡牌。"""
        random1 = FixedRandomSource(rolls=[1, 2, 3])
        random2 = FixedRandomSource(rolls=[1, 2, 3])
        card1 = draw_card("chance", random1)
        card2 = draw_card("chance", random2)
        assert card1["id"] == card2["id"]
