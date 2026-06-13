"""基础权威回合引擎测试。

覆盖 Task 7 验收标准：
- 非当前玩家不能掷骰
- 客户端不能指定点数
- 固定随机源得到确定结果
- 经过起点加钱
- 双数额外回合
- 三次双数进监狱
- 普通落点推进到下一玩家
- 每个有效命令版本加一
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


def _fixed_dice(d1: int, d2: int) -> FixedRandomSource:
    return FixedRandomSource(rolls=[d1, d2])


# ---------------------------------------------------------------------------
# 测试：非当前玩家不能掷骰
# ---------------------------------------------------------------------------


class TestNotCurrentPlayer:
    def test_non_current_player_cannot_roll(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        result = apply_command(
            game=game,
            actor_id=players[1].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 4),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "NOT_CURRENT_PLAYER" for e in result.events)


# ---------------------------------------------------------------------------
# 测试：客户端不能指定点数
# ---------------------------------------------------------------------------


class TestClientCannotSpecifyDice:
    def test_payload_with_dice_values_ignored(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        random = _fixed_dice(3, 4)
        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={"d1": 6, "d2": 6},
            random_source=random,
            now=datetime.now(),
            players=players,
        )
        # 骰子值来自随机源，不是 payload
        assert result.changed is True
        assert game.last_dice == (3, 4)


# ---------------------------------------------------------------------------
# 测试：固定随机源得到确定结果
# ---------------------------------------------------------------------------


class TestDeterministicRandom:
    def test_fixed_random_source_gives_same_result(self):
        # 使用独立的玩家列表避免共享状态
        players1 = [_make_player(seat=0), _make_player(seat=1)]
        players2 = [_make_player(seat=0), _make_player(seat=1)]
        game1 = _make_game(players1)
        game2 = _make_game(players2)

        r1 = _fixed_dice(5, 2)
        r2 = _fixed_dice(5, 2)

        apply_command(
            game=game1,
            actor_id=players1[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=r1,
            now=datetime.now(),
            players=players1,
        )
        apply_command(
            game=game2,
            actor_id=players2[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=r2,
            now=datetime.now(),
            players=players2,
        )
        assert game1.last_dice == game2.last_dice
        assert game1.phase == game2.phase


# ---------------------------------------------------------------------------
# 测试：经过起点加钱
# ---------------------------------------------------------------------------


class TestPassGo:
    def test_pass_go_adds_money(self):
        players = [_make_player(seat=0, money=15000), _make_player(seat=1)]
        game = _make_game(players)
        # 玩家在位置 38，掷出 (1,2)=3，经过位置 0（起点）
        players[0].position = 38
        initial_money = players[0].money

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(1, 2),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        # 38 + 3 = 41 → 41 % 40 = 1，经过起点
        assert players[0].position == 1
        assert players[0].money == initial_money + 2000


# ---------------------------------------------------------------------------
# 测试：双数额外回合
# ---------------------------------------------------------------------------


class TestDoublesExtraTurn:
    def test_doubles_gives_extra_turn(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        # 设置位置使得 (3,3)=6 落到免费停车 position=20
        # 从 position 14 掷出 6 = position 20
        players[0].position = 14

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 3),  # 双数
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        # 双数后当前玩家不变，阶段回到 WAITING_FOR_ROLL
        assert game.current_player_id == players[0].id
        assert game.phase == TurnPhase.WAITING_FOR_ROLL
        assert players[0].consecutive_doubles == 1


# ---------------------------------------------------------------------------
# 测试：三次双数进监狱
# ---------------------------------------------------------------------------


class TestThreeDoublesJail:
    def test_three_consecutive_doubles_goes_to_jail(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        players[0].consecutive_doubles = 2  # 已经连续两次双数

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(2, 2),  # 第三次双数
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        assert players[0].in_jail is True
        assert players[0].position == 10  # 监狱位置
        assert players[0].consecutive_doubles == 0
        # 进监狱后轮到下一玩家
        assert game.current_player_id == players[1].id


# ---------------------------------------------------------------------------
# 测试：普通落点推进到下一玩家
# ---------------------------------------------------------------------------


class TestNormalTurnAdvance:
    def test_non_doubles_advances_to_next_player(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        # 从 position 16 掷出 (2,2)=4 到 position 20（免费停车，无决策）
        # 但 (2,2) 是双数，改用 (3,4)=7 从 position 13 到 position 20
        players[0].position = 13

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 4),  # 非双数
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        assert game.current_player_id == players[1].id
        assert game.phase == TurnPhase.WAITING_FOR_ROLL
        assert players[0].consecutive_doubles == 0


# ---------------------------------------------------------------------------
# 测试：每个有效命令版本加一
# ---------------------------------------------------------------------------


class TestVersionIncrement:
    def test_effective_command_increments_version(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        # 从 position 13 掷出 (3,4)=7 到 position 20（免费停车，无决策）
        players[0].position = 13
        assert game.turn_number == 0

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 4),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        assert game.turn_number == 1

    def test_ineffective_command_does_not_increment_version(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_command(
            game=game,
            actor_id=players[1].id,  # 非当前玩家
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 4),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is False
        assert game.turn_number == 0


# ---------------------------------------------------------------------------
# 测试：错误阶段不能掷骰
# ---------------------------------------------------------------------------


class TestWrongPhase:
    def test_cannot_roll_in_wrong_phase(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)
        game.phase = TurnPhase.AWAITING_PROPERTY_DECISION

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 4),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is False
        assert any(e["code"] == "INVALID_PHASE" for e in result.events)


# ---------------------------------------------------------------------------
# 测试：EngineResult 结构
# ---------------------------------------------------------------------------


class TestEngineResult:
    def test_engine_result_has_events(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 4),
            now=datetime.now(),
            players=players,
        )
        assert result.changed is True
        assert isinstance(result.events, list)
        assert len(result.events) > 0
        # 至少有一个 dice_rolled 事件
        assert any(e.get("type") == "dice_rolled" for e in result.events)

    def test_engine_result_no_private_events_for_roll(self):
        players = [_make_player(seat=0), _make_player(seat=1)]
        game = _make_game(players)

        result = apply_command(
            game=game,
            actor_id=players[0].id,
            command=CommandName.ROLL_DICE,
            payload={},
            random_source=_fixed_dice(3, 4),
            now=datetime.now(),
            players=players,
        )
        # 掷骰不应产生私密事件
        assert result.private_events == {}
