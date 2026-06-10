"""Task 1 测试：冻结服务端共享棋盘常量。

旧版对照测试通过正则解析 monopoly.html 中的 SPACES、COLOR_GROUPS、
HOUSE_COST 和 RENT_MULTIPLIER 常量，确保服务端数据与旧版完全一致。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.engine.board import (
    BOARD_SIZE,
    COLOR_GROUPS,
    HOUSE_COST,
    RENT_MULTIPLIER,
    SPACES,
    Space,
)

# ---------------------------------------------------------------------------
# 旧版 HTML 解析工具
# ---------------------------------------------------------------------------

_HTML_PATH = Path(__file__).resolve().parent.parent.parent / "monopoly.html"


def _read_html() -> str:
    return _HTML_PATH.read_text(encoding="utf-8")


def _parse_legacy_spaces(html: str) -> list[dict]:
    """从 monopoly.html 提取 SPACES 数组中每个对象的字段。"""
    match = re.search(r"const SPACES = \[([\s\S]*?)\];", html)
    assert match, "无法在 monopoly.html 中找到 SPACES 定义"
    body = match.group(1)

    spaces: list[dict] = []
    # 匹配每个 { ... } 对象
    for obj_match in re.finditer(r"\{([^}]+)\}", body):
        obj_text = obj_match.group(1)
        entry: dict = {}

        # type
        m = re.search(r"type:\s*'([^']+)'", obj_text)
        if m:
            entry["type"] = m.group(1)

        # name
        m = re.search(r"name:\s*'([^']+)'", obj_text)
        if m:
            entry["name"] = m.group(1)

        # group
        m = re.search(r"group:\s*(null|'[^']*')", obj_text)
        if m:
            entry["group"] = None if m.group(1) == "null" else m.group(1).strip("'")

        # price
        m = re.search(r"price:\s*(null|\d+)", obj_text)
        if m:
            entry["price"] = None if m.group(1) == "null" else int(m.group(1))

        # baseRent
        m = re.search(r"baseRent:\s*(null|\d+)", obj_text)
        if m:
            entry["baseRent"] = None if m.group(1) == "null" else int(m.group(1))

        # icon (optional)
        m = re.search(r"icon:\s*'([^']+)'", obj_text)
        if m:
            entry["icon"] = m.group(1)

        spaces.append(entry)
    return spaces


def _parse_legacy_color_groups(html: str) -> dict[str, list[int]]:
    match = re.search(r"const COLOR_GROUPS = \{([\s\S]*?)\};", html)
    assert match, "无法在 monopoly.html 中找到 COLOR_GROUPS 定义"
    body = match.group(1)
    result: dict[str, list[int]] = {}
    for m in re.finditer(r"(\w+):\s*\[([^\]]+)\]", body):
        key = m.group(1)
        values = [int(x.strip()) for x in m.group(2).split(",")]
        result[key] = values
    return result


def _parse_legacy_house_cost(html: str) -> dict[str, int]:
    match = re.search(r"const HOUSE_COST = \{([\s\S]*?)\};", html)
    assert match, "无法在 monopoly.html 中找到 HOUSE_COST 定义"
    body = match.group(1)
    result: dict[str, int] = {}
    for m in re.finditer(r"(\w+):\s*(\d+)", body):
        result[m.group(1)] = int(m.group(2))
    return result


def _parse_legacy_rent_multiplier(html: str) -> list[int]:
    match = re.search(r"const RENT_MULTIPLIER = \[([^\]]+)\];", html)
    assert match, "无法在 monopoly.html 中找到 RENT_MULTIPLIER 定义"
    return [int(x.strip()) for x in match.group(1).split(",")]


# ---------------------------------------------------------------------------
# 基本结构测试
# ---------------------------------------------------------------------------


class TestBoardStructure:
    def test_board_has_forty_spaces(self):
        assert len(SPACES) == 40

    def test_board_size_constant(self):
        assert BOARD_SIZE == 40

    def test_start_position_is_go(self):
        assert SPACES[0].type == "go"

    def test_jail_position(self):
        assert SPACES[10].type == "jail"

    def test_space_position_matches_index(self):
        for i, space in enumerate(SPACES):
            assert space.position == i

    def test_every_color_group_references_properties(self):
        for positions in COLOR_GROUPS.values():
            assert positions
            assert all(SPACES[pos].type == "property" for pos in positions)

    def test_space_is_frozen_dataclass(self):
        s = SPACES[0]
        with pytest.raises(AttributeError):
            s.position = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 旧版对照测试
# ---------------------------------------------------------------------------


class TestLegacyConsistency:
    """从 monopoly.html 结构化解析常量并与服务端 board.py 逐项比对。"""

    @pytest.fixture(scope="class")
    def html(self):
        return _read_html()

    @pytest.fixture(scope="class")
    def legacy_spaces(self, html):
        return _parse_legacy_spaces(html)

    @pytest.fixture(scope="class")
    def legacy_color_groups(self, html):
        return _parse_legacy_color_groups(html)

    @pytest.fixture(scope="class")
    def legacy_house_cost(self, html):
        return _parse_legacy_house_cost(html)

    @pytest.fixture(scope="class")
    def legacy_rent_multiplier(self, html):
        return _parse_legacy_rent_multiplier(html)

    def test_space_count_matches_legacy(self, legacy_spaces):
        assert len(SPACES) == len(legacy_spaces)

    def test_space_types_match_legacy(self, legacy_spaces):
        for i, legacy in enumerate(legacy_spaces):
            assert SPACES[i].type == legacy["type"], (
                f"Space {i}: type mismatch: server={SPACES[i].type!r}, legacy={legacy['type']!r}"
            )

    def test_space_names_match_legacy(self, legacy_spaces):
        for i, legacy in enumerate(legacy_spaces):
            assert SPACES[i].name == legacy["name"], (
                f"Space {i}: name mismatch: server={SPACES[i].name!r}, legacy={legacy['name']!r}"
            )

    def test_space_groups_match_legacy(self, legacy_spaces):
        for i, legacy in enumerate(legacy_spaces):
            assert SPACES[i].group == legacy["group"], (
                f"Space {i}: group mismatch: server={SPACES[i].group!r}, legacy={legacy['group']!r}"
            )

    def test_space_prices_match_legacy(self, legacy_spaces):
        for i, legacy in enumerate(legacy_spaces):
            assert SPACES[i].price == legacy["price"], (
                f"Space {i}: price mismatch: server={SPACES[i].price!r}, legacy={legacy['price']!r}"
            )

    def test_space_base_rents_match_legacy(self, legacy_spaces):
        for i, legacy in enumerate(legacy_spaces):
            assert SPACES[i].base_rent == legacy["baseRent"], (
                f"Space {i}: baseRent mismatch: server={SPACES[i].base_rent!r}, legacy={legacy['baseRent']!r}"
            )

    def test_space_icons_match_legacy(self, legacy_spaces):
        for i, legacy in enumerate(legacy_spaces):
            expected_icon = legacy.get("icon")
            assert SPACES[i].icon == expected_icon, (
                f"Space {i}: icon mismatch: server={SPACES[i].icon!r}, legacy={expected_icon!r}"
            )

    def test_color_groups_match_legacy(self, legacy_color_groups):
        assert set(COLOR_GROUPS.keys()) == set(legacy_color_groups.keys())
        for group in legacy_color_groups:
            assert COLOR_GROUPS[group] == legacy_color_groups[group], (
                f"COLOR_GROUPS[{group!r}]: server={COLOR_GROUPS[group]}, legacy={legacy_color_groups[group]}"
            )

    def test_house_cost_matches_legacy(self, legacy_house_cost):
        assert set(HOUSE_COST.keys()) == set(legacy_house_cost.keys())
        for group in legacy_house_cost:
            assert HOUSE_COST[group] == legacy_house_cost[group], (
                f"HOUSE_COST[{group!r}]: server={HOUSE_COST[group]}, legacy={legacy_house_cost[group]}"
            )

    def test_rent_multiplier_matches_legacy(self, legacy_rent_multiplier):
        assert list(RENT_MULTIPLIER) == legacy_rent_multiplier
