"""落点规则测试。

覆盖 Task 8 验收标准：
- 无主地产 → AWAITING_PROPERTY_DECISION
- 购买扣款登记所有权
- 放弃 → AUCTION 阶段
- 有主非抵押地产正确计算租金（普通/色组/建筑）
- 抵押地产不收租
- 税费进 free_parking_money
- 起点/免费停车无决策
- Go To Jail 即进监
- 机会/命运卡牌触发
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from server.engine.board import BOARD_SIZE, SPACES
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


def _roll_dice(game: GameState, players: list[PlayerState], d1: int, d2: int) -> EngineResult:
    """用指定骰子值掷骰。"""
    return apply_command(
        game=game,
        actor_id=players[0].id,
        command=CommandName.ROLL_DICE,
        payload={},
        random_source=FixedRandomSource(rolls=[d1, d2]),
        now=datetime.now(),
        players=players,
    )


def _land_on(game: GameState, players: list[PlayerState], target_pos: int) -> EngineResult:
    """将玩家0移动到指定位置并触发落点逻辑。

    设置玩家位置到 target_pos 前一个位置，然后掷骰到达。
    如果 target_pos 为 0，从位置 38 掷出 (1,1) 到达。
    """
    # 计算从哪个位置出发需要掷出什么骰子
    # 选择一个出发位置，使得 d1+d2 = target_pos - start (mod 40)
    # 简单方法：从 target_pos - 3 出发，掷出 (1, 2)
    start = (target_pos - 3) % BOARD_SIZE
    players[0].position = start
    return _roll_dice(game, players, 1, 2)


# ---------------------------------------------------------------------------
# 测试：无主地产 → AWAITING_PROPERTY_DECISION
# ---------------------------------------------------------------------------


class TestUnownedProperty:
    def test_landing_on_unowned_property_awaits_decision(self):
        """落地无主地产时，阶段变为 AWAITING_PROPERTY_DECISION。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 郊区小径 position=1, price=600
        # 从 position 38 出发，掷出 (2,1) 到达 position 1（经过起点）
        players[0].position = 38
        result = _roll_dice(game, players, 2, 1)
        assert game.phase == TurnPhase.AWAITING_PROPERTY_DECISION
        assert game.pending_decision is not None
        assert game.pending_decision["type"] == "property_decision"
        assert game.pending_decision["position"] == 1

    def test_cannot_afford_property_goes_to_auction(self):
        """资金不足时直接进入拍卖阶段。"""
        players = [_make_player(seat=0, money=100), _make_player(seat=1)]
        game = _make_game(players)
        # 郊区小径 position=1, price=600，玩家只有 $100
        # 从 position 38 出发，掷出 (2,1) 到达 position 1（经过起点加 2000）
        # 经过起点后玩家有 2100，可以购买，所以需要不经过起点
        # 从 position 38 出发，掷出 (1,2) = 3，到达 position 1（经过起点）
        # 改用不经过起点的路径：从 position 38 出发到 position 1 必须经过起点
        # 改用 position 5（山谷道 price=600），从 position 2 掷出 (2,1)
        players[0].position = 2
        result = _roll_dice(game, players, 2, 1)
        assert game.phase == TurnPhase.AUCTION


# ---------------------------------------------------------------------------
# 测试：购买扣款登记所有权
# ---------------------------------------------------------------------------


class TestBuyProperty:
    def test_buy_property_deducts_money_and_registers_ownership(self):
        """BUY_PROPERTY 扣款、登记所有权、添加到玩家地产列表。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 先落地到无主地产 position=1
        players[0].position = 38
        _roll_dice(game, players, 2, 1)
        assert game.phase == TurnPhase.AWAITING_PROPERTY_DECISION

        initial_money = players[0].money
        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.BUY_PROPERTY,
            payload={},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        space = SPACES[1]
        assert players[0].money == initial_money - space.price
        assert game.property_owners[1] == players[0].id
        assert 1 in players[0].properties


# ---------------------------------------------------------------------------
# 测试：放弃 → AUCTION 阶段
# ---------------------------------------------------------------------------


class TestDeclineProperty:
    def test_decline_property_enters_auction(self):
        """DECLINE_PROPERTY 进入拍卖阶段。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        players[0].position = 38
        _roll_dice(game, players, 2, 1)
        assert game.phase == TurnPhase.AWAITING_PROPERTY_DECISION

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.DECLINE_PROPERTY,
            payload={},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        assert game.phase == TurnPhase.AUCTION


# ---------------------------------------------------------------------------
# 测试：有主非抵押地产租金
# ---------------------------------------------------------------------------


class TestRentCollection:
    def test_basic_rent_on_owned_property(self):
        """落地有主非抵押地产，支付基础租金。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        # 设置 position 1 的所有者为玩家 2
        game.property_owners[1] = players[1].id
        players[1].properties.append(1)

        # 从 position 38 掷出 (2,1) 到达 position 1
        players[0].position = 38
        initial_p0_money = players[0].money
        initial_p1_money = players[1].money

        result = _roll_dice(game, players, 2, 1)
        # 经过起点加 2000，然后支付租金
        space = SPACES[1]
        assert players[0].money == initial_p0_money + 2000 - space.base_rent
        assert players[1].money == initial_p1_money + space.base_rent

    def test_monopoly_doubles_rent(self):
        """完整色组垄断且无建筑时，租金翻倍。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        # 玩家2拥有 brown 组全部（position 1 和 3）
        game.property_owners[1] = players[1].id
        game.property_owners[3] = players[1].id
        players[1].properties.extend([1, 3])

        players[0].position = 38
        initial_p0_money = players[0].money
        initial_p1_money = players[1].money

        result = _roll_dice(game, players, 2, 1)
        space = SPACES[1]
        # 经过起点加 2000，垄断翻倍租金
        assert players[0].money == initial_p0_money + 2000 - space.base_rent * 2
        assert players[1].money == initial_p1_money + space.base_rent * 2

    def test_building_rent_uses_multiplier(self):
        """有建筑时租金 = base_rent × RENT_MULTIPLIER[level]。"""
        from server.engine.board import RENT_MULTIPLIER

        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        # 玩家2拥有 brown 组全部 + 2栋建筑
        game.property_owners[1] = players[1].id
        game.property_owners[3] = players[1].id
        players[1].properties.extend([1, 3])
        game.building_levels[1] = 2  # 公寓

        players[0].position = 38
        initial_p0_money = players[0].money
        initial_p1_money = players[1].money

        result = _roll_dice(game, players, 2, 1)
        space = SPACES[1]
        expected_rent = space.base_rent * RENT_MULTIPLIER[2]  # 60 * 6 = 360
        assert players[0].money == initial_p0_money + 2000 - expected_rent
        assert players[1].money == initial_p1_money + expected_rent

    def test_mortgaged_property_no_rent(self):
        """抵押地产不收租。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1, money=15000)]
        game = _make_game(players)
        # 玩家2拥有 position 1 但已抵押
        game.property_owners[1] = players[1].id
        players[1].properties.append(1)
        game.mortgage_status[1] = True

        players[0].position = 38
        initial_p0_money = players[0].money
        initial_p1_money = players[1].money

        result = _roll_dice(game, players, 2, 1)
        # 抵押不收租，只加经过起点的钱
        assert players[0].money == initial_p0_money + 2000
        assert players[1].money == initial_p1_money


# ---------------------------------------------------------------------------
# 测试：税费进 free_parking_money
# ---------------------------------------------------------------------------


class TestTax:
    def test_income_tax_goes_to_free_parking(self):
        """所得税进入免费停车奖金池。"""
        players = [_make_player(seat=0, money=10000), _make_player(seat=1)]
        game = _make_game(players)
        # 所得税 position=4，从 position 1 掷出 (2,1)
        players[0].position = 1
        result = _roll_dice(game, players, 2, 1)
        # 所得税 = max(200, min(2000, money * 0.1))
        # 掷骰后经过 position 4，但实际位置是 1+3=4
        # 注意：落地 position 4 时 money 可能已经变了（如果之前经过起点）
        # 从 position 1 掷出 3，到达 position 4
        expected_tax = max(200, min(2000, int(10000 * 0.1)))
        assert game.free_parking_money == expected_tax
        assert players[0].money == 10000 - expected_tax

    def test_luxury_tax_below_threshold(self):
        """豪宅税：建筑不到8不收税。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 给玩家0一些地产和建筑（4栋，不到8）
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        game.building_levels[1] = 4
        # 豪宅税 position=38，从 position 35 掷出 (2,1)
        players[0].position = 35
        result = _roll_dice(game, players, 2, 1)
        assert game.free_parking_money == 0  # 不到8栋不收


# ---------------------------------------------------------------------------
# 测试：起点/免费停车无决策
# ---------------------------------------------------------------------------


class TestGoAndFreeParking:
    def test_free_parking_no_decision(self):
        """免费停车无决策，回合正常推进。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 免费停车 position=20，从 position 17 掷出 (2,1)
        players[0].position = 17
        result = _roll_dice(game, players, 2, 1)
        # 免费停车无决策，回合推进到下一玩家
        assert game.phase == TurnPhase.WAITING_FOR_ROLL
        assert game.current_player_id == players[1].id


# ---------------------------------------------------------------------------
# 测试：Go To Jail 即进监
# ---------------------------------------------------------------------------


class TestGoToJail:
    def test_landing_on_go_to_jail(self):
        """落地 Go To Jail 立即进监狱。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # Go To Jail position=30，从 position 27 掷出 (2,1)
        players[0].position = 27
        result = _roll_dice(game, players, 2, 1)
        assert players[0].in_jail is True
        assert players[0].position == 10
        assert players[0].consecutive_doubles == 0
        # 进监狱后推进到下一玩家
        assert game.current_player_id == players[1].id


# ---------------------------------------------------------------------------
# 测试：机会/命运卡牌触发
# ---------------------------------------------------------------------------


class TestCardSpaces:
    def test_landing_on_chance_triggers_card(self):
        """落地机会空间触发卡牌。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 机会 position=7，从 position 4 掷出 (2,1)
        players[0].position = 4
        result = _roll_dice(game, players, 2, 1)
        # 应该触发卡牌
        assert any(e.get("type") == "card_drawn" for e in result.events)

    def test_landing_on_destiny_triggers_card(self):
        """落地命运空间触发卡牌。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 命运 position=2，从 position 39 掷出 (2,1) → 经过起点到 position 2
        players[0].position = 39
        result = _roll_dice(game, players, 2, 1)
        assert any(e.get("type") == "card_drawn" for e in result.events)


# ---------------------------------------------------------------------------
# 测试：BUY_PROPERTY 阶段校验
# ---------------------------------------------------------------------------


class TestBuyPropertyPhaseValidation:
    def test_cannot_buy_in_wrong_phase(self):
        """非 AWAITING_PROPERTY_DECISION 阶段不能购买。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.WAITING_FOR_ROLL

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.BUY_PROPERTY,
            payload={},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)

    def test_non_current_player_cannot_buy(self):
        """非当前玩家不能购买。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AWAITING_PROPERTY_DECISION
        game.pending_decision = {"type": "property_decision", "position": 1, "playerId": str(players[0].id)}

        result = apply_command(
            game=game,
            actor_id=players[1].id,
            command=CommandName.BUY_PROPERTY,
            payload={},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_CURRENT_PLAYER" for e in result.events)

    def test_insufficient_funds_cannot_buy(self):
        """资金不足不能购买。"""
        players = [_make_player(seat=0, money=100), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AWAITING_PROPERTY_DECISION
        game.pending_decision = {"type": "property_decision", "position": 1, "playerId": str(players[0].id)}

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.BUY_PROPERTY,
            payload={},
            random_source=FixedRandomSource(rolls=[1, 2]),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INSUFFICIENT_FUNDS" for e in result.events)
