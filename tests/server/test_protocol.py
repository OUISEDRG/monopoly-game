"""Task 3 测试：客户端命令协议、错误码枚举和命令结果信封。

覆盖 ClientCommand 解析校验、CommandName 枚举、ErrorCode 枚举、
消息大小限制、结果构造器和异常分类。
"""

from __future__ import annotations

import json
import typing
from uuid import uuid4

import pytest

from server.protocol import (
    ClientCommand,
    CommandName,
    ErrorCode,
    accepted_result,
    parse_client_command,
    rejected_result,
)


# ---------------------------------------------------------------------------
# CommandName 枚举
# ---------------------------------------------------------------------------


class TestCommandName:
    EXPECTED_NAMES = {
        "SET_READY",
        "START_GAME",
        "LEAVE_ROOM",
        "ROLL_DICE",
        "PROPOSE_TRADE",
        "BUILD",
        "SELL_BUILDING",
        "MORTGAGE",
        "UNMORTGAGE",
        "BUY_PROPERTY",
        "DECLINE_PROPERTY",
        "PLACE_BID",
        "PASS_AUCTION",
        "ACCEPT_TRADE",
        "REJECT_TRADE",
        "COUNTER_TRADE",
        "DEBT_ACTION",
    }

    def test_all_command_names_defined(self):
        defined = {e.name for e in CommandName}
        assert defined == self.EXPECTED_NAMES

    def test_no_extra_commands(self):
        defined = {e.name for e in CommandName}
        assert defined == self.EXPECTED_NAMES


# ---------------------------------------------------------------------------
# ErrorCode 枚举
# ---------------------------------------------------------------------------


class TestErrorCode:
    EXPECTED_CODES = {
        "INVALID_MESSAGE",
        "INVALID_NICKNAME",
        "ROOM_NOT_FOUND",
        "ROOM_FULL",
        "ROOM_ALREADY_STARTED",
        "NICKNAME_TAKEN",
        "AUTH_FAILED",
        "NOT_HOST",
        "NOT_READY",
        "NOT_CURRENT_PLAYER",
        "INVALID_PHASE",
        "INVALID_COMMAND",
        "STALE_STATE",
        "DUPLICATE_REQUEST",
        "INSUFFICIENT_FUNDS",
        "ASSET_CHANGED",
        "RATE_LIMITED",
    }

    def test_all_error_codes_defined(self):
        defined = {e.name for e in ErrorCode}
        assert defined == self.EXPECTED_CODES


# ---------------------------------------------------------------------------
# ClientCommand 解析 — 正常路径
# ---------------------------------------------------------------------------


class TestParseClientCommandSuccess:
    def _make_raw(self, **overrides) -> str:
        base = {
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "ROLL_DICE",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_valid_command_with_payload(self):
        raw = self._make_raw(payload={"foo": "bar"})
        cmd = parse_client_command(raw)
        assert cmd.command == CommandName.ROLL_DICE
        assert cmd.payload == {"foo": "bar"}

    def test_valid_command_without_payload(self):
        raw = self._make_raw()
        cmd = parse_client_command(raw)
        assert cmd.payload == {}

    def test_request_id_preserved(self):
        rid = str(uuid4())
        raw = self._make_raw(requestId=rid)
        cmd = parse_client_command(raw)
        assert str(cmd.request_id) == rid

    def test_room_version_preserved(self):
        raw = self._make_raw(roomVersion=42)
        cmd = parse_client_command(raw)
        assert cmd.room_version == 42

    def test_type_must_be_command(self):
        raw = self._make_raw(type="command")
        cmd = parse_client_command(raw)
        assert cmd.type == "command"

    def test_all_command_names_parseable(self):
        for cn in CommandName:
            raw = self._make_raw(command=cn.value)
            cmd = parse_client_command(raw)
            assert cmd.command == cn


# ---------------------------------------------------------------------------
# ClientCommand 解析 — 协议校验失败
# ---------------------------------------------------------------------------


class TestParseClientCommandValidation:
    def _make_raw(self, **overrides) -> str:
        base = {
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "ROLL_DICE",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command("not json")

    def test_top_level_not_object(self):
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(json.dumps([1, 2, 3]))

    def test_unknown_command(self):
        with pytest.raises(ValueError, match="INVALID_COMMAND"):
            parse_client_command(self._make_raw(command="FLY_TO_MOON"))

    def test_missing_request_id(self):
        raw = json.dumps({
            "type": "command",
            "roomVersion": 1,
            "command": "ROLL_DICE",
        })
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    def test_invalid_uuid(self):
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(self._make_raw(requestId="not-a-uuid"))

    def test_negative_room_version(self):
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(self._make_raw(roomVersion=-1))

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(self._make_raw(type="event"))

    def test_unknown_top_level_field(self):
        raw = json.dumps({
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "ROLL_DICE",
            "evilField": "hack",
        })
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    def test_no_internal_stack_trace_in_error(self):
        """校验失败不得泄露内部堆栈。"""
        try:
            parse_client_command("not json")
        except ValueError as e:
            assert "Traceback" not in str(e)
            assert "File " not in str(e)


# ---------------------------------------------------------------------------
# 消息大小限制
# ---------------------------------------------------------------------------


class TestMessageSizeLimit:
    def _make_raw(self, **overrides) -> str:
        base = {
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "ROLL_DICE",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_exactly_16kib_not_rejected(self):
        """恰好 16 KiB 不应仅因大小被拒绝。"""
        target = 16 * 1024
        # 先构造带短 payload 的命令，再逐步增大直到恰好 16 KiB
        pad_str = "x"
        raw = self._make_raw(payload={"pad": pad_str})
        current = len(raw.encode("utf-8"))
        # 每多一个 x 字符，UTF-8 大小增 1
        if current < target:
            pad_str = "x" * (len(pad_str) + target - current)
            raw = self._make_raw(payload={"pad": pad_str})
        # 精确调整
        while len(raw.encode("utf-8")) < target:
            pad_str += "x"
            raw = self._make_raw(payload={"pad": pad_str})
        while len(raw.encode("utf-8")) > target:
            pad_str = pad_str[:-1]
            raw = self._make_raw(payload={"pad": pad_str})
        assert len(raw.encode("utf-8")) == target
        cmd = parse_client_command(raw)
        assert cmd.command == CommandName.ROLL_DICE

    def test_over_16kib_rejected(self):
        """超过 16 KiB 必须被拒绝。"""
        base_size = len(self._make_raw().encode("utf-8"))
        padding_needed = 16 * 1024 - base_size + 1
        pad_str = "x" * max(0, padding_needed)
        raw = self._make_raw(payload={"pad": pad_str})
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)


# ---------------------------------------------------------------------------
# 结果构造器
# ---------------------------------------------------------------------------


class TestAcceptedResult:
    def test_structure(self):
        rid = uuid4()
        result = accepted_result(rid, room_version=43)
        assert result["type"] == "command_result"
        assert result["requestId"] == str(rid)
        assert result["accepted"] is True
        assert result["roomVersion"] == 43

    def test_no_error_field(self):
        rid = uuid4()
        result = accepted_result(rid, room_version=43)
        assert "error" not in result

    def test_json_serializable(self):
        rid = uuid4()
        result = accepted_result(rid, room_version=43)
        text = json.dumps(result)
        assert isinstance(text, str)


class TestRejectedResult:
    def test_structure(self):
        rid = uuid4()
        result = rejected_result(
            rid,
            room_version=43,
            code=ErrorCode.NOT_CURRENT_PLAYER,
            message="当前不是你的回合",
        )
        assert result["type"] == "command_result"
        assert result["requestId"] == str(rid)
        assert result["accepted"] is False
        assert result["roomVersion"] == 43
        assert result["error"]["code"] == "NOT_CURRENT_PLAYER"
        assert result["error"]["message"] == "当前不是你的回合"

    def test_uuid_converted_to_string(self):
        rid = uuid4()
        result = rejected_result(
            rid,
            room_version=1,
            code=ErrorCode.STALE_STATE,
            message="stale",
        )
        assert isinstance(result["requestId"], str)

    def test_error_code_is_string_value(self):
        rid = uuid4()
        result = rejected_result(
            rid,
            room_version=1,
            code=ErrorCode.RATE_LIMITED,
            message="too fast",
        )
        assert isinstance(result["error"]["code"], str)
        assert result["error"]["code"] == "RATE_LIMITED"

    def test_json_serializable(self):
        rid = uuid4()
        result = rejected_result(
            rid,
            room_version=1,
            code=ErrorCode.ROOM_FULL,
            message="full",
        )
        text = json.dumps(result)
        assert isinstance(text, str)

    def test_does_not_modify_room_version(self):
        """结果构造器不得改变房间版本号。"""
        rid = uuid4()
        v = 42
        result = rejected_result(
            rid,
            room_version=v,
            code=ErrorCode.INVALID_COMMAND,
            message="bad",
        )
        assert result["roomVersion"] == v


# ---------------------------------------------------------------------------
# 返修测试：Literal 类型、严格整数、签名、稳定分类、隔离、UTF-8、精确键集合
# ---------------------------------------------------------------------------


class TestLiteralType:
    def test_type_annotation_is_literal(self):
        """ClientCommand.type 必须声明为 Literal["command"]。"""
        hints = typing.get_type_hints(ClientCommand)
        origin = getattr(hints["type"], "__origin__", None)
        assert origin is typing.Literal


class TestStrictRoomVersion:
    def _make_raw(self, **overrides) -> str:
        base = {
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "ROLL_DICE",
        }
        base.update(overrides)
        return json.dumps(base)

    def test_string_version_rejected(self):
        """JSON 字符串 "1" 不得被接受为 roomVersion。"""
        raw = self._make_raw(roomVersion="1")
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    def test_float_version_rejected(self):
        """JSON 浮点 1.0 不得被接受为 roomVersion。"""
        raw = self._make_raw(roomVersion=1.0)
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    def test_true_version_rejected(self):
        """JSON 布尔 true 不得被接受为 roomVersion。"""
        raw = self._make_raw(roomVersion=True)
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    def test_false_version_rejected(self):
        """JSON 布尔 false 不得被接受为 roomVersion。"""
        raw = self._make_raw(roomVersion=False)
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    def test_zero_version_accepted(self):
        """合法整数 0 必须可接受。"""
        raw = self._make_raw(roomVersion=0)
        cmd = parse_client_command(raw)
        assert cmd.room_version == 0

    def test_positive_version_accepted(self):
        """合法正整数必须可接受。"""
        raw = self._make_raw(roomVersion=42)
        cmd = parse_client_command(raw)
        assert cmd.room_version == 42


class TestRejectedResultSignature:
    def test_code_keyword_argument(self):
        """rejected_result 必须接受 code= 关键字参数。"""
        rid = uuid4()
        result = rejected_result(
            rid,
            room_version=1,
            code=ErrorCode.STALE_STATE,
            message="stale",
        )
        assert result["error"]["code"] == "STALE_STATE"


class TestStableCommandClassification:
    def _make_raw(self, command_value: object) -> str:
        return json.dumps({
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": command_value,
        })

    def test_unknown_command_returns_invalid_command(self):
        """未知命令必须稳定返回 INVALID_COMMAND，不依赖英文异常文本。"""
        raw = self._make_raw("FLY_TO_MOON")
        with pytest.raises(ValueError, match="INVALID_COMMAND"):
            parse_client_command(raw)

    def test_missing_command_returns_invalid_message(self):
        """缺失 command 字段必须返回 INVALID_MESSAGE。"""
        raw = json.dumps({
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
        })
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    @pytest.mark.parametrize("value", [[], {"key": "val"}, 1, True, False, None])
    def test_non_string_command_returns_invalid_message(self, value: object):
        """非字符串 command 值必须返回 INVALID_MESSAGE，不得泄露 TypeError。"""
        raw = self._make_raw(value)
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)

    @pytest.mark.parametrize("value", [[], {"key": "val"}, 1, True, False, None])
    def test_non_string_command_no_stack_trace(self, value: object):
        """非字符串 command 校验失败不得泄露堆栈或 Pydantic 内部细节。"""
        raw = self._make_raw(value)
        try:
            parse_client_command(raw)
        except ValueError as e:
            msg = str(e)
            assert "Traceback" not in msg
            assert "TypeError" not in msg
            assert "unhashable" not in msg


class TestPayloadIsolation:
    def test_payload_default_isolation(self):
        """两个解析结果的 payload 必须是独立字典。"""
        raw1 = json.dumps({
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "ROLL_DICE",
        })
        raw2 = json.dumps({
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "BUILD",
        })
        cmd1 = parse_client_command(raw1)
        cmd2 = parse_client_command(raw2)
        cmd1.payload["test_key"] = "test_value"
        assert "test_key" not in cmd2.payload


class TestChineseUTF8Boundary:
    def _make_raw(self, **overrides) -> str:
        base = {
            "type": "command",
            "requestId": str(uuid4()),
            "roomVersion": 1,
            "command": "ROLL_DICE",
        }
        base.update(overrides)
        return json.dumps(base, ensure_ascii=False)

    def test_exactly_16384_bytes_chinese(self):
        """恰好 16384 字节（含中文 UTF-8 多字节）不应被拒绝。"""
        target = 16384
        # 中文字符在 UTF-8 中占 3 字节
        pad_str = "你"
        raw = self._make_raw(payload={"pad": pad_str})
        current = len(raw.encode("utf-8"))
        # 逐步增加中文填充
        if current < target:
            extra_needed = (target - current) // 3 + 2
            pad_str = "你" * extra_needed
            raw = self._make_raw(payload={"pad": pad_str})
        # 精确调整：用 ASCII 字符微调
        while len(raw.encode("utf-8")) > target:
            # 减少 payload 中的内容
            data = json.loads(raw)
            pad = data["payload"]["pad"]
            if len(pad) > 1:
                data["payload"]["pad"] = pad[:-1]
            else:
                break
            raw = json.dumps(data, ensure_ascii=False)
        while len(raw.encode("utf-8")) < target:
            data = json.loads(raw)
            data["payload"]["pad"] = data["payload"].get("pad", "") + "x"
            raw = json.dumps(data, ensure_ascii=False)
        assert len(raw.encode("utf-8")) == target
        cmd = parse_client_command(raw)
        assert cmd.command == CommandName.ROLL_DICE

    def test_over_16384_bytes_chinese_rejected(self):
        """超过 16384 字节必须被拒绝。"""
        # 构造超过 16384 字节的中文字符串
        pad_str = "你" * 6000  # 约 18000 字节
        raw = self._make_raw(payload={"pad": pad_str})
        assert len(raw.encode("utf-8")) > 16384
        with pytest.raises(ValueError, match="INVALID_MESSAGE"):
            parse_client_command(raw)


class TestResultExactKeys:
    def test_accepted_result_exact_keys(self):
        """accepted_result 必须恰好包含 4 个键。"""
        rid = uuid4()
        result = accepted_result(rid, room_version=1)
        assert set(result.keys()) == {"type", "requestId", "accepted", "roomVersion"}

    def test_rejected_result_exact_keys(self):
        """rejected_result 必须恰好包含 5 个键。"""
        rid = uuid4()
        result = rejected_result(
            rid,
            room_version=1,
            code=ErrorCode.ROOM_FULL,
            message="full",
        )
        assert set(result.keys()) == {"type", "requestId", "accepted", "roomVersion", "error"}

    def test_error_object_exact_keys(self):
        """error 对象必须恰好包含 code 和 message。"""
        rid = uuid4()
        result = rejected_result(
            rid,
            room_version=1,
            code=ErrorCode.INVALID_PHASE,
            message="wrong phase",
        )
        assert set(result["error"].keys()) == {"code", "message"}
