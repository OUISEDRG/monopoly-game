"""Task 2 测试：权威状态模型与公共快照。

覆盖枚举定义、dataclass 默认值、可变字段隔离、
公共快照序列化和私密数据泄露防护。
"""

from __future__ import annotations

import json
import dataclasses
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from server.models.game import GameState, TurnPhase
from server.models.player import PlayerState
from server.models.room import RoomPhase, RoomState, build_public_snapshot


# ---------------------------------------------------------------------------
# 枚举测试
# ---------------------------------------------------------------------------


class TestRoomPhase:
    def test_lobby_value(self):
        assert RoomPhase.LOBBY == "lobby"

    def test_playing_value(self):
        assert RoomPhase.PLAYING == "playing"

    def test_finished_value(self):
        assert RoomPhase.FINISHED == "finished"


class TestTurnPhase:
    def test_waiting_for_roll_value(self):
        assert TurnPhase.WAITING_FOR_ROLL == "waiting_for_roll"

    def test_resolving_move_value(self):
        assert TurnPhase.RESOLVING_MOVE == "resolving_move"

    def test_awaiting_property_decision_value(self):
        assert TurnPhase.AWAITING_PROPERTY_DECISION == "awaiting_property_decision"

    def test_awaiting_card_decision_value(self):
        assert TurnPhase.AWAITING_CARD_DECISION == "awaiting_card_decision"

    def test_auction_value(self):
        assert TurnPhase.AUCTION == "auction"

    def test_trade_negotiation_value(self):
        assert TurnPhase.TRADE_NEGOTIATION == "trade_negotiation"

    def test_debt_relief_value(self):
        assert TurnPhase.DEBT_RELIEF == "debt_relief"

    def test_turn_end_value(self):
        assert TurnPhase.TURN_END == "turn_end"

    def test_game_over_value(self):
        assert TurnPhase.GAME_OVER == "game_over"


# ---------------------------------------------------------------------------
# PlayerState 测试
# ---------------------------------------------------------------------------


class TestPlayerState:
    def test_default_money_is_15000(self):
        """起始资金必须与 monopoly.html 一致：15000。"""
        p = PlayerState(id=uuid4(), nickname="Alice", seat=0, color="#e74c3c")
        assert p.money == 15000

    def test_default_position(self):
        p = PlayerState(id=uuid4(), nickname="Alice", seat=0, color="#e74c3c")
        assert p.position == 0

    def test_default_jail_state(self):
        p = PlayerState(id=uuid4(), nickname="Alice", seat=0, color="#e74c3c")
        assert p.in_jail is False
        assert p.jail_turns == 0
        assert p.has_get_out_of_jail_card is False

    def test_default_bankrupt(self):
        p = PlayerState(id=uuid4(), nickname="Alice", seat=0, color="#e74c3c")
        assert p.bankrupt is False

    def test_default_connected(self):
        p = PlayerState(id=uuid4(), nickname="Alice", seat=0, color="#e74c3c")
        assert p.connected is True

    def test_default_consecutive_doubles(self):
        p = PlayerState(id=uuid4(), nickname="Alice", seat=0, color="#e74c3c")
        assert p.consecutive_doubles == 0

    def test_mutable_fields_isolated(self):
        """两个 PlayerState 实例的 properties 列表必须独立。"""
        p1 = PlayerState(id=uuid4(), nickname="A", seat=0, color="#e74c3c")
        p2 = PlayerState(id=uuid4(), nickname="B", seat=1, color="#3498db")
        p1.properties.append(5)
        assert 5 not in p2.properties


# ---------------------------------------------------------------------------
# GameState 测试
# ---------------------------------------------------------------------------


class TestGameState:
    def test_initial_phase(self):
        gs = GameState(current_player_id=uuid4())
        assert gs.phase == TurnPhase.WAITING_FOR_ROLL

    def test_default_turn_number(self):
        gs = GameState(current_player_id=uuid4())
        assert gs.turn_number == 0

    def test_default_free_parking_money(self):
        gs = GameState(current_player_id=uuid4())
        assert gs.free_parking_money == 0

    def test_default_trade_window_available(self):
        gs = GameState(current_player_id=uuid4())
        assert gs.trade_window_available is True

    def test_mutable_fields_isolated(self):
        gs1 = GameState(current_player_id=uuid4())
        gs2 = GameState(current_player_id=uuid4())
        gs1.property_owners[5] = uuid4()
        assert 5 not in gs2.property_owners


# ---------------------------------------------------------------------------
# RoomState 测试
# ---------------------------------------------------------------------------


class TestRoomState:
    def test_default_phase(self):
        r = RoomState(code="ABC123", host_player_id=uuid4())
        assert r.phase == RoomPhase.LOBBY

    def test_default_version(self):
        r = RoomState(code="ABC123", host_player_id=uuid4())
        assert r.version == 0

    def test_mutable_fields_isolated(self):
        r1 = RoomState(code="A1", host_player_id=uuid4())
        r2 = RoomState(code="B2", host_player_id=uuid4())
        r1.players.append(PlayerState(id=uuid4(), nickname="X", seat=0, color="#e74c3c"))
        assert len(r2.players) == 0

    def test_no_token_hash_secret_fields(self):
        """RoomState 的 dataclass 字段不得包含 token/hash/secret。"""
        for f in dataclasses.fields(RoomState):
            fname = f.name.lower()
            assert "token" not in fname, f"字段 {f.name} 含 'token'"
            assert "hash" not in fname, f"字段 {f.name} 含 'hash'"
            assert "secret" not in fname, f"字段 {f.name} 含 'secret'"


# ---------------------------------------------------------------------------
# 公共快照测试
# ---------------------------------------------------------------------------


class TestPublicSnapshot:
    def _make_room(self, **overrides) -> RoomState:
        defaults = dict(code="TEST01", host_player_id=uuid4())
        defaults.update(overrides)
        return RoomState(**defaults)

    def test_snapshot_contains_room_version(self):
        room = self._make_room(version=7)
        snap = build_public_snapshot(room, server_time_ms=1000)
        assert snap["roomVersion"] == 7

    def test_snapshot_contains_server_time(self):
        room = self._make_room()
        snap = build_public_snapshot(room, server_time_ms=9999)
        assert snap["serverTime"] == 9999

    def test_snapshot_is_json_serializable(self):
        room = self._make_room()
        room.players.append(
            PlayerState(id=uuid4(), nickname="Alice", seat=0, color="#e74c3c")
        )
        room.game = GameState(current_player_id=uuid4())
        snap = build_public_snapshot(room, server_time_ms=1000)
        text = json.dumps(snap)
        assert isinstance(text, str)

    def test_snapshot_uuid_converted_to_string(self):
        pid = uuid4()
        room = self._make_room(host_player_id=pid)
        snap = build_public_snapshot(room, server_time_ms=1000)
        assert isinstance(snap["state"]["hostPlayerId"], str)
        assert snap["state"]["hostPlayerId"] == str(pid)

    def test_snapshot_enum_converted_to_string(self):
        room = self._make_room()
        snap = build_public_snapshot(room, server_time_ms=1000)
        assert isinstance(snap["state"]["phase"], str)
        assert snap["state"]["phase"] == "lobby"

    def test_snapshot_datetime_converted_to_iso(self):
        now = datetime(2026, 6, 11, 5, 0, 0, tzinfo=timezone.utc)
        room = self._make_room(created_at=now)
        snap = build_public_snapshot(room, server_time_ms=1000)
        assert isinstance(snap["state"]["createdAt"], str)

    def test_snapshot_tuple_converted_to_list(self):
        """last_dice 是 tuple，快照中应为 list。"""
        pid = uuid4()
        room = self._make_room()
        room.game = GameState(current_player_id=pid, last_dice=(3, 5))
        snap = build_public_snapshot(room, server_time_ms=1000)
        game_state = snap["state"]["game"]
        assert isinstance(game_state["lastDice"], list)
        assert game_state["lastDice"] == [3, 5]

    def test_token_hash_not_in_snapshot(self):
        """私密令牌哈希存于独立身份记录，不在 RoomState 中，也不在快照中。"""
        secret_hash = "deadbeefcafebabe" * 4
        # 私密身份记录独立于 RoomState
        reconnect_tokens: dict[UUID, str] = {uuid4(): secret_hash}
        room = self._make_room()
        snap = build_public_snapshot(room, server_time_ms=1000)
        snap_text = json.dumps(snap)
        assert secret_hash not in snap_text

    def test_snapshot_excludes_runtime_objects(self):
        """快照不得包含 lock、WebSocket 或请求缓存。"""
        room = self._make_room()
        snap = build_public_snapshot(room, server_time_ms=1000)
        snap_text = json.dumps(snap).lower()
        for forbidden in ["lock", "socket", "websocket", "request_id", "processed"]:
            assert forbidden not in snap_text

    def test_envelope_top_level_keys(self):
        """快照顶层必须恰好是协议信封：type, roomVersion, serverTime, state。"""
        room = self._make_room()
        snap = build_public_snapshot(room, server_time_ms=1000)
        assert set(snap.keys()) == {"type", "roomVersion", "serverTime", "state"}
        assert snap["type"] == "state_snapshot"

    def test_state_inner_no_envelope_metadata(self):
        """内部 state 不得包含 type、roomVersion、serverTime 或重复的 version。"""
        room = self._make_room()
        snap = build_public_snapshot(room, server_time_ms=1000)
        inner = snap["state"]
        for forbidden_key in ("type", "roomVersion", "serverTime", "version"):
            assert forbidden_key not in inner, f"state 内含禁止键 '{forbidden_key}'"

    def test_snapshot_with_debt_state_json_serializable(self):
        """game.debt = DebtState(...) 时可被 json.dumps() 成功序列化。"""
        from server.engine.debt import DebtState

        pid = uuid4()
        room = self._make_room()
        room.game = GameState(current_player_id=pid)
        room.game.debt = DebtState(player_id=pid, creditor_id=None, owed_amount=500)
        snap = build_public_snapshot(room, server_time_ms=1000)
        text = json.dumps(snap)
        assert isinstance(text, str)
        assert "restore_callback" not in text

    def test_snapshot_with_auction_state_json_serializable(self):
        """game.auction = AuctionState(...) 时可被 json.dumps() 成功序列化。"""
        room = self._make_room()
        pid = uuid4()
        room.game = GameState(current_player_id=pid)
        from server.engine.auction import AuctionState

        room.game.auction = AuctionState(
            position=1,
            starting_price=100,
            highest_bid=100,
            highest_bidder_id=None,
            current_bidder_seat=0,
            active_bidders={pid},
            bid_order=[pid],
        )
        snap = build_public_snapshot(room, server_time_ms=1000)
        text = json.dumps(snap)
        assert isinstance(text, str)

    def test_snapshot_with_trade_state_json_serializable(self):
        """game.trade = TradeState(...) 时可被 json.dumps() 成功序列化。"""
        from server.engine.trade import TradeOffer, TradeState

        pid = uuid4()
        tid = uuid4()
        room = self._make_room()
        room.game = GameState(current_player_id=pid)
        room.game.trade = TradeState(
            initiator_id=pid,
            target_id=tid,
            initiator_offer=TradeOffer(properties=[1], cash=100),
            target_offer=TradeOffer(properties=[3], cash=50),
            counter_rounds=0,
            current_responder=tid,
        )
        snap = build_public_snapshot(room, server_time_ms=1000)
        text = json.dumps(snap)
        assert isinstance(text, str)

    def test_snapshot_debt_excludes_restore_callback(self):
        """DebtState 序列化不得夹带 Callable 字段。"""
        from server.engine.debt import DebtState

        pid = uuid4()
        room = self._make_room()
        room.game = GameState(current_player_id=pid)
        room.game.debt = DebtState(
            player_id=pid, creditor_id=None, owed_amount=500,
            restore_callback=lambda g, p: [{"type": "test"}],
        )
        snap = build_public_snapshot(room, server_time_ms=1000)
        text = json.dumps(snap)
        assert isinstance(text, str)
        assert "restore_callback" not in text

    def test_snapshot_debt_public_keys_no_privacy_leak(self):
        """DebtState 公共快照只含预期字段，不暴露内部回调上下文。"""
        from server.engine.debt import DebtState

        pid = uuid4()
        room = self._make_room()
        room.game = GameState(current_player_id=pid)
        room.game.debt = DebtState(player_id=pid, creditor_id=None, owed_amount=500)
        snap = build_public_snapshot(room, server_time_ms=1000)
        debt_dict = snap["state"]["game"]["debt"]
        expected_keys = {"playerId", "creditorId", "owedAmount", "deadline", "completed"}
        assert set(debt_dict.keys()) == expected_keys
