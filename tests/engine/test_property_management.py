"""建造、出售建筑和抵押规则测试。

覆盖验收标准：
- BUILD: 仅 WAITING_FOR_ROLL + 当前玩家；须完整色组、无抵押、平均建设
- SELL_BUILDING: 退款 50%，平均出售
- MORTGAGE: 扣抵押价值、阻止收租和建造
- UNMORTGAGE: 付抵押价值 × 1.1 解押
- 覆盖完整色组、抵押阻止、平均建设/出售、资金不足、解押、非法所有者、阶段/玩家校验
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from server.engine.board import COLOR_GROUPS, HOUSE_COST, SPACES
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


def _own_full_group(game: GameState, player: PlayerState, group: str) -> None:
    """让玩家拥有完整色组的所有地产。"""
    for pos in COLOR_GROUPS[group]:
        game.property_owners[pos] = player.id
        if pos not in player.properties:
            player.properties.append(pos)


def _fixed_dice(d1: int, d2: int) -> FixedRandomSource:
    return FixedRandomSource(rolls=[d1, d2])


# ---------------------------------------------------------------------------
# BUILD 命令测试
# ---------------------------------------------------------------------------


class TestBuildPhaseAndPlayer:
    """BUILD 仅 WAITING_FOR_ROLL + 当前玩家。"""

    def test_build_wrong_phase_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AWAITING_PROPERTY_DECISION
        _own_full_group(game, players[0], "brown")

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)

    def test_build_not_current_player_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[1], "brown")

        result = apply_command(
            game=game, actor_id=players[1].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_CURRENT_PLAYER" for e in result.events)


class TestBuildCompleteColorGroup:
    """BUILD 须完整色组。"""

    def test_build_incomplete_group_rejected(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        # 只拥有 brown 的一个地产
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INCOMPLETE_COLOR_GROUP" for e in result.events)

    def test_build_complete_group_succeeds(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.building_levels[1] == 1
        assert players[0].money == 15000 - HOUSE_COST["brown"]


class TestBuildMortgageBlocks:
    """BUILD 色组内有抵押地产时阻止建造。"""

    def test_build_mortgaged_group_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")
        # 抵押色组中的一个地产
        game.mortgage_status[3] = True

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "MORTGAGED_PROPERTY" for e in result.events)


class TestBuildEvenBuilding:
    """BUILD 平均建设（同色组差 ≤ 1）。"""

    def test_build_uneven_rejected(self):
        """orange 色组 [11, 13, 14]，11 已有 1 级，不能在 11 再建。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "orange")
        game.building_levels[11] = 1  # 11 有 1 级，13 和 14 为 0

        # 在 11 再建会导致 11=2, 13=0, 14=0，差 > 1
        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 11}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "UNEVEN_BUILDING" for e in result.events)

    def test_build_even_succeeds(self):
        """先在 13 建，再在 11 建是允许的（都是 1 级）。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "orange")
        game.building_levels[13] = 1

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 11}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.building_levels[11] == 1


class TestBuildInsufficientFunds:
    """BUILD 资金不足。"""

    def test_build_insufficient_funds_rejected(self):
        players = [_make_player(seat=0, money=100), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INSUFFICIENT_FUNDS" for e in result.events)


class TestBuildMaxLevel:
    """BUILD 最大等级 4。"""

    def test_build_max_level_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")
        game.building_levels[1] = 4

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "MAX_LEVEL_REACHED" for e in result.events)


class TestBuildNotOwner:
    """BUILD 非所有者。"""

    def test_build_not_owner_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 位置 1 属于玩家 1
        game.property_owners[1] = players[1].id

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)


class TestBuildMissingPosition:
    """BUILD 缺少 position。"""

    def test_build_missing_position_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)


# ---------------------------------------------------------------------------
# SELL_BUILDING 命令测试
# ---------------------------------------------------------------------------


class TestSellBuildingRefund:
    """SELL_BUILDING 退款 50%。"""

    def test_sell_refund_half(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")
        game.building_levels[1] = 1
        game.building_levels[3] = 1
        initial_money = players[0].money

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.SELL_BUILDING,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        expected_refund = HOUSE_COST["brown"] // 2
        assert players[0].money == initial_money + expected_refund
        assert game.building_levels[1] == 0


class TestSellBuildingEvenSelling:
    """SELL_BUILDING 平均出售。"""

    def test_sell_uneven_rejected(self):
        """orange [11,13,14]，11=2, 13=1, 14=1，不能卖 13（13=0, 11=2 差>1）。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "orange")
        game.building_levels[11] = 2
        game.building_levels[13] = 1
        game.building_levels[14] = 1

        # 卖 13 会导致 11=2, 13=0, 差 > 1
        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.SELL_BUILDING,
            payload={"position": 13}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "UNEVEN_SELLING" for e in result.events)

    def test_sell_even_succeeds(self):
        """orange [11,13,14]，全部 1 级，卖 13 是允许的。"""
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "orange")
        game.building_levels[11] = 1
        game.building_levels[13] = 1
        game.building_levels[14] = 1

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.SELL_BUILDING,
            payload={"position": 13}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.building_levels[13] == 0


class TestSellBuildingNoBuilding:
    """SELL_BUILDING 无建筑可卖。"""

    def test_sell_no_building_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.SELL_BUILDING,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NO_BUILDING" for e in result.events)


class TestSellBuildingNotOwner:
    """SELL_BUILDING 非所有者。"""

    def test_sell_not_owner_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[1].id
        game.building_levels[1] = 1

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.SELL_BUILDING,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)


class TestSellBuildingPhaseAndPlayer:
    """SELL_BUILDING 阶段和玩家校验。"""

    def test_sell_wrong_phase_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AWAITING_PROPERTY_DECISION
        _own_full_group(game, players[0], "brown")
        game.building_levels[1] = 1

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.SELL_BUILDING,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)

    def test_sell_not_current_player_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[1], "brown")
        game.building_levels[1] = 1

        result = apply_command(
            game=game, actor_id=players[1].id, command=CommandName.SELL_BUILDING,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_CURRENT_PLAYER" for e in result.events)


# ---------------------------------------------------------------------------
# MORTGAGE 命令测试
# ---------------------------------------------------------------------------


class TestMortgageValue:
    """MORTGAGE 获得抵押价值（地产价格的一半）。"""

    def test_mortgage_adds_value(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        initial_money = players[0].money

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.MORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        expected_value = SPACES[1].price // 2  # 600 // 2 = 300
        assert players[0].money == initial_money + expected_value
        assert game.mortgage_status[1] is True


class TestMortgageBlocksRentAndBuild:
    """MORTGAGE 阻止收租和建造。"""

    def test_mortgaged_property_blocks_build(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")
        game.mortgage_status[3] = True

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "MORTGAGED_PROPERTY" for e in result.events)


class TestMortgageHasBuildings:
    """MORTGAGE 有建筑不能抵押。"""

    def test_mortgage_with_buildings_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        game.building_levels[1] = 2

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.MORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "HAS_BUILDINGS" for e in result.events)


class TestMortgageAlreadyMortgaged:
    """MORTGAGE 已抵押不能重复抵押。"""

    def test_mortgage_already_mortgaged_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        game.mortgage_status[1] = True

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.MORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "ALREADY_MORTGAGED" for e in result.events)


class TestMortgageNotOwner:
    """MORTGAGE 非所有者。"""

    def test_mortgage_not_owner_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[1].id

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.MORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)


class TestMortgagePhaseAndPlayer:
    """MORTGAGE 阶段和玩家校验。"""

    def test_mortgage_wrong_phase_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AUCTION
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.MORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)


# ---------------------------------------------------------------------------
# UNMORTGAGE 命令测试
# ---------------------------------------------------------------------------


class TestUnmortgageCost:
    """UNMORTGAGE 付抵押价值 × 1.1 解押。"""

    def test_unmortgage_pays_110_percent(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        game.mortgage_status[1] = True
        initial_money = players[0].money

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.UNMORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        mortgage_value = SPACES[1].price // 2  # 300
        expected_cost = int(mortgage_value * 1.1)  # 330
        assert players[0].money == initial_money - expected_cost
        assert game.mortgage_status[1] is False


class TestUnmortgageInsufficientFunds:
    """UNMORTGAGE 资金不足。"""

    def test_unmortgage_insufficient_funds_rejected(self):
        players = [_make_player(seat=0, money=10), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        game.mortgage_status[1] = True

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.UNMORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INSUFFICIENT_FUNDS" for e in result.events)


class TestUnmortgageNotMortgaged:
    """UNMORTGAGE 未抵押不能解押。"""

    def test_unmortgage_not_mortgaged_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        # 未设置抵押

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.UNMORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_MORTGAGED" for e in result.events)


class TestUnmortgageNotOwner:
    """UNMORTGAGE 非所有者。"""

    def test_unmortgage_not_owner_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.property_owners[1] = players[1].id
        game.mortgage_status[1] = True

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.UNMORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_COMMAND" for e in result.events)


class TestUnmortgagePhaseAndPlayer:
    """UNMORTGAGE 阶段和玩家校验。"""

    def test_unmortgage_wrong_phase_rejected(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AUCTION
        game.property_owners[1] = players[0].id
        players[0].properties.append(1)
        game.mortgage_status[1] = True

        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.UNMORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)


# ---------------------------------------------------------------------------
# 集成场景：抵押 → 阻止建造 → 解押 → 可建造
# ---------------------------------------------------------------------------


class TestMortgageUnmortgageBuildFlow:
    """抵押后不能建造，解押后可以建造。"""

    def test_mortgage_blocks_build_then_unmortgage_allows_build(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")

        # 抵押 position 3
        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.MORTGAGE,
            payload={"position": 3}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.mortgage_status[3] is True

        # 尝试建造 position 1，被拒绝
        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is False

        # 解押 position 3
        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.UNMORTGAGE,
            payload={"position": 3}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.mortgage_status[3] is False

        # 现在可以建造
        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.building_levels[1] == 1


# ---------------------------------------------------------------------------
# 集成场景：建造 → 出售 → 抵押
# ---------------------------------------------------------------------------


class TestBuildSellMortgageFlow:
    """建造后出售，然后可以抵押。"""

    def test_build_then_sell_then_mortgage(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        _own_full_group(game, players[0], "brown")

        # 建造
        apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        apply_command(
            game=game, actor_id=players[0].id, command=CommandName.BUILD,
            payload={"position": 3}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert game.building_levels[1] == 1
        assert game.building_levels[3] == 1

        # 出售
        apply_command(
            game=game, actor_id=players[0].id, command=CommandName.SELL_BUILDING,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert game.building_levels[1] == 0

        # 抵押
        result = apply_command(
            game=game, actor_id=players[0].id, command=CommandName.MORTGAGE,
            payload={"position": 1}, random_source=_fixed_dice(1, 2),
            now=datetime.now(), players=players,
        )
        assert result.changed is True
        assert game.mortgage_status[1] is True
