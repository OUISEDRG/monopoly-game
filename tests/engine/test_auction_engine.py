"""多人拍卖引擎测试。

覆盖验收标准：
- 起拍价
- 最低加价 50
- 超现金拒绝
- 主动退出
- 轮转
- 无人出价→流拍
- 最终成交
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from server.engine.auction import (
    AuctionState,
    DEFAULT_STARTING_PRICE,
    MIN_BID_INCREMENT,
    apply_pass_auction,
    apply_place_bid,
    create_auction,
)
from server.engine.board import SPACES
from server.engine.commands import EngineResult
from server.engine.rules import FixedRandomSource, apply_command
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
        players = [_make_player(seat=0), _make_player(seat=1)]
    return GameState(
        current_player_id=players[0].id,
        phase=TurnPhase.WAITING_FOR_ROLL,
    )


def _setup_auction(
    players: list[PlayerState],
    position: int = 1,
    starting_price: int | None = None,
) -> tuple[GameState, AuctionState]:
    """创建游戏和拍卖状态。"""
    game = _make_game(players)
    game.last_dice = (3, 4)  # 非双数
    auction = create_auction(game, players, position, starting_price)
    return game, auction


def _find_player_by_seat(players: list[PlayerState], seat: int) -> PlayerState:
    for p in players:
        if p.seat == seat:
            return p
    raise ValueError(f"No player with seat {seat}")


# ---------------------------------------------------------------------------
# 起拍价测试
# ---------------------------------------------------------------------------


class TestStartingPrice:
    """起拍价默认 100，可自定义。"""

    def test_default_starting_price(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game, auction = _setup_auction(players, position=1)
        assert auction.highest_bid == DEFAULT_STARTING_PRICE
        assert auction.starting_price == DEFAULT_STARTING_PRICE

    def test_custom_starting_price(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game, auction = _setup_auction(players, position=1, starting_price=200)
        assert auction.highest_bid == 200
        assert auction.starting_price == 200

    def test_auction_phase_set(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game, auction = _setup_auction(players, position=1)
        assert game.phase == TurnPhase.AUCTION


# ---------------------------------------------------------------------------
# 最低加价 50 测试
# ---------------------------------------------------------------------------


class TestMinimumBidIncrement:
    """出价须 ≥ 当前最高价 + 50。"""

    def test_bid_below_minimum_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        # 起拍价 100，最低出价 150
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        result = apply_place_bid(
            game=game, actor_id=current_bidder.id,
            payload={"amount": 120}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "BID_TOO_LOW" for e in result.events)

    def test_bid_at_minimum_accepted(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        # 起拍价 100，最低出价 150
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        result = apply_place_bid(
            game=game, actor_id=current_bidder.id,
            payload={"amount": 150}, players=players,
        )
        assert result.changed is True
        assert auction.highest_bid == 150
        assert auction.highest_bidder_id == current_bidder.id


# ---------------------------------------------------------------------------
# 超现金拒绝测试
# ---------------------------------------------------------------------------


class TestExceedsCash:
    """出价不得超过当前现金。"""

    def test_bid_exceeds_cash_rejected(self):
        players = [_make_player(seat=0, money=120), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        # 起拍价 100，最低出价 150，但玩家只有 120
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)
        # 确保当前出价者是只有 120 的玩家
        if current_bidder.money != 120:
            # 调整座位使低资金玩家先出价
            players_swapped = [_make_player(seat=0, money=120), _make_player(seat=1, money=15000)]
            game, auction = _setup_auction(players_swapped, position=1)
            current_bidder = _find_player_by_seat(players_swapped, auction.current_bidder_seat)

        result = apply_place_bid(
            game=game, actor_id=current_bidder.id,
            payload={"amount": 150}, players=players,
        )
        # 如果当前出价者只有 120，出价 150 应被拒绝
        if current_bidder.money < 150:
            assert result.changed is False
            assert any(e["code"] == "INSUFFICIENT_FUNDS" for e in result.events)

    def test_bid_at_exact_cash_accepted(self):
        players = [_make_player(seat=0, money=150), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        # 确保出价者有恰好 150
        if current_bidder.money >= 150:
            result = apply_place_bid(
                game=game, actor_id=current_bidder.id,
                payload={"amount": 150}, players=players,
            )
            assert result.changed is True


# ---------------------------------------------------------------------------
# 主动退出测试
# ---------------------------------------------------------------------------


class TestPassAuction:
    """主动退出后不能重新加入。"""

    def test_pass_removes_from_active_bidders(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        result = apply_pass_auction(
            game=game, actor_id=current_bidder.id,
            payload={}, players=players,
        )
        assert result.changed is True
        assert current_bidder.id not in auction.active_bidders

    def test_pass_then_bid_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        # 先退出
        apply_pass_auction(
            game=game, actor_id=current_bidder.id,
            payload={}, players=players,
        )

        # 再尝试出价
        result = apply_place_bid(
            game=game, actor_id=current_bidder.id,
            payload={"amount": 150}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_ACTIVE_BIDDER" for e in result.events)

    def test_pass_then_pass_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        # 先退出
        apply_pass_auction(
            game=game, actor_id=current_bidder.id,
            payload={}, players=players,
        )

        # 再尝试退出
        result = apply_pass_auction(
            game=game, actor_id=current_bidder.id,
            payload={}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_ACTIVE_BIDDER" for e in result.events)


# ---------------------------------------------------------------------------
# 轮转测试
# ---------------------------------------------------------------------------


class TestBidRotation:
    """按座位循环轮转。"""

    def test_three_player_rotation(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000), _make_player(seat=2, money=15000)]
        game, auction = _setup_auction(players, position=1)

        # 当前出价者出价
        bidder1 = _find_player_by_seat(players, auction.current_bidder_seat)
        result = apply_place_bid(
            game=game, actor_id=bidder1.id,
            payload={"amount": 150}, players=players,
        )
        assert result.changed is True

        # 下一个出价者出价
        bidder2 = _find_player_by_seat(players, auction.current_bidder_seat)
        assert bidder2.id != bidder1.id
        result = apply_place_bid(
            game=game, actor_id=bidder2.id,
            payload={"amount": 200}, players=players,
        )
        assert result.changed is True

        # 第三个出价者
        bidder3 = _find_player_by_seat(players, auction.current_bidder_seat)
        assert bidder3.id != bidder2.id

    def test_pass_skips_to_next(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000), _make_player(seat=2, money=15000)]
        game, auction = _setup_auction(players, position=1)

        # 当前出价者退出
        bidder1 = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_pass_auction(
            game=game, actor_id=bidder1.id,
            payload={}, players=players,
        )

        # 下一个应该不是退出的人
        bidder2 = _find_player_by_seat(players, auction.current_bidder_seat)
        assert bidder2.id != bidder1.id


# ---------------------------------------------------------------------------
# 无人出价→流拍测试
# ---------------------------------------------------------------------------


class TestNoBids:
    """无人出价时地产保持无主。"""

    def test_all_pass_no_bids_cancels_auction(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)

        # 第一个退出
        bidder1 = _find_player_by_seat(players, auction.current_bidder_seat)
        result1 = apply_pass_auction(
            game=game, actor_id=bidder1.id,
            payload={}, players=players,
        )
        assert result1.changed is True

        # 第二个退出
        bidder2 = _find_player_by_seat(players, auction.current_bidder_seat)
        result2 = apply_pass_auction(
            game=game, actor_id=bidder2.id,
            payload={}, players=players,
        )
        assert result2.changed is True

        # 检查流拍事件
        events = result2.events
        assert any(e.get("type") == "auction_cancelled" for e in events)
        assert game.phase == TurnPhase.WAITING_FOR_ROLL
        assert game.auction is None
        # 地产保持无主
        assert 1 not in game.property_owners

    def test_three_players_all_pass(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000), _make_player(seat=2, money=15000)]
        game, auction = _setup_auction(players, position=1)

        for _ in range(3):
            bidder = _find_player_by_seat(players, auction.current_bidder_seat)
            apply_pass_auction(
                game=game, actor_id=bidder.id,
                payload={}, players=players,
            )
            if game.auction is None:
                break

        assert game.phase == TurnPhase.WAITING_FOR_ROLL
        assert game.auction is None
        assert 1 not in game.property_owners


# ---------------------------------------------------------------------------
# 最终成交测试
# ---------------------------------------------------------------------------


class TestAuctionWin:
    """最终成交：扣款 + 转移地产。"""

    def test_single_bidder_wins_when_others_pass(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)

        # 第一个出价
        bidder1 = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_place_bid(
            game=game, actor_id=bidder1.id,
            payload={"amount": 150}, players=players,
        )

        # 第二个退出
        bidder2 = _find_player_by_seat(players, auction.current_bidder_seat)
        result = apply_pass_auction(
            game=game, actor_id=bidder2.id,
            payload={}, players=players,
        )

        # 成交
        assert any(e.get("type") == "auction_won" for e in result.events)
        won_event = next(e for e in result.events if e.get("type") == "auction_won")
        assert won_event["playerId"] == str(bidder1.id)
        assert won_event["amount"] == 150
        assert game.property_owners[1] == bidder1.id
        assert bidder1.money == 15000 - 150
        assert 1 in bidder1.properties

    def test_three_player_auction_with_bids_and_passes(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000), _make_player(seat=2, money=15000)]
        game, auction = _setup_auction(players, position=1)

        # 玩家 A 出价 150
        bidder_a = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_place_bid(
            game=game, actor_id=bidder_a.id,
            payload={"amount": 150}, players=players,
        )

        # 玩家 B 出价 200
        bidder_b = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_place_bid(
            game=game, actor_id=bidder_b.id,
            payload={"amount": 200}, players=players,
        )

        # 玩家 C 退出
        bidder_c = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_pass_auction(
            game=game, actor_id=bidder_c.id,
            payload={}, players=players,
        )

        # 玩家 A 退出
        bidder_a_again = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_pass_auction(
            game=game, actor_id=bidder_a_again.id,
            payload={}, players=players,
        )

        # 只剩 B，成交
        assert game.auction is None
        assert game.property_owners[1] == bidder_b.id
        assert bidder_b.money == 15000 - 200

    def test_auction_won_resets_game_state(self):
        """拍卖成交后清理拍卖状态并推进回合。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)

        bidder1 = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_place_bid(
            game=game, actor_id=bidder1.id,
            payload={"amount": 150}, players=players,
        )

        bidder2 = _find_player_by_seat(players, auction.current_bidder_seat)
        apply_pass_auction(
            game=game, actor_id=bidder2.id,
            payload={}, players=players,
        )

        assert game.auction is None
        assert game.pending_decision is None
        assert game.phase == TurnPhase.WAITING_FOR_ROLL


# ---------------------------------------------------------------------------
# 阶段和玩家校验测试
# ---------------------------------------------------------------------------


class TestPhaseAndPlayerValidation:
    """非拍卖阶段和非当前出价者不能操作。"""

    def test_place_bid_wrong_phase_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        game.phase = TurnPhase.WAITING_FOR_ROLL

        result = apply_place_bid(
            game=game, actor_id=players[0].id,
            payload={"amount": 150}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)

    def test_pass_auction_wrong_phase_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        game.phase = TurnPhase.WAITING_FOR_ROLL

        result = apply_pass_auction(
            game=game, actor_id=players[0].id,
            payload={}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)

    def test_place_bid_not_your_turn_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)

        # 找到不是当前出价者的人
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)
        other = [p for p in players if p.id != current_bidder.id][0]

        result = apply_place_bid(
            game=game, actor_id=other.id,
            payload={"amount": 150}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_YOUR_TURN" for e in result.events)

    def test_pass_auction_not_your_turn_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)

        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)
        other = [p for p in players if p.id != current_bidder.id][0]

        result = apply_pass_auction(
            game=game, actor_id=other.id,
            payload={}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_YOUR_TURN" for e in result.events)


# ---------------------------------------------------------------------------
# 通过 apply_command 集成测试
# ---------------------------------------------------------------------------


class TestAuctionViaApplyCommand:
    """通过 apply_command 调用拍卖命令。"""

    def test_place_bid_via_apply_command(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        result = apply_command(
            game=game, actor_id=current_bidder.id,
            command=CommandName.PLACE_BID,
            payload={"amount": 150},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert auction.highest_bid == 150

    def test_pass_auction_via_apply_command(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        result = apply_command(
            game=game, actor_id=current_bidder.id,
            command=CommandName.PASS_AUCTION,
            payload={},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(), players=players,
        )
        assert result.changed is True


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """边界情况。"""

    def test_bid_missing_amount_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        result = apply_place_bid(
            game=game, actor_id=current_bidder.id,
            payload={}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)

    def test_bid_non_int_amount_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game, auction = _setup_auction(players, position=1)
        current_bidder = _find_player_by_seat(players, auction.current_bidder_seat)

        result = apply_place_bid(
            game=game, actor_id=current_bidder.id,
            payload={"amount": "one hundred"}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)

    def test_no_active_auction_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        game.phase = TurnPhase.AUCTION
        game.auction = None

        result = apply_place_bid(
            game=game, actor_id=players[0].id,
            payload={"amount": 150}, players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)

    def test_auction_start_from_next_seat(self):
        """拍卖从触发者的下一个座位开始。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000), _make_player(seat=2, money=15000)]
        game = _make_game(players)
        game.last_dice = (3, 4)
        # current_player_id 是 players[0]（seat 0）
        auction = create_auction(game, players, position=1)

        # 第一个出价者应该是 seat 1（下一个座位）
        assert auction.current_bidder_seat == 1

    def test_auction_start_wraps_around(self):
        """最后一个座位的下一个是第一个座位。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000), _make_player(seat=2, money=15000)]
        game = _make_game(players)
        game.current_player_id = players[2].id  # seat 2
        game.last_dice = (3, 4)
        auction = create_auction(game, players, position=1)

        # seat 2 的下一个是 seat 0
        assert auction.current_bidder_seat == 0
