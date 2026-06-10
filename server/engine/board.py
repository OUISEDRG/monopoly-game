"""服务端权威棋盘常量。

从 monopoly.html 逐项迁移，数值和名称必须与旧版完全一致。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 棋盘大小
# ---------------------------------------------------------------------------

BOARD_SIZE: int = 40

# ---------------------------------------------------------------------------
# 颜色组 → 地产位置列表
# ---------------------------------------------------------------------------

COLOR_GROUPS: dict[str, list[int]] = {
    "brown": [1, 3],
    "lightBlue": [5, 6],
    "pink": [8, 9],
    "orange": [11, 13, 14],
    "red": [16, 17, 19],
    "yellow": [21, 23, 24],
    "green": [26, 27, 29],
    "darkBlue": [31, 32],
    "gold": [34, 36],
}

# ---------------------------------------------------------------------------
# 建房费用（规则文档第115-118行）
# ---------------------------------------------------------------------------

HOUSE_COST: dict[str, int] = {
    "brown": 500,
    "lightBlue": 500,
    "pink": 500,
    "orange": 1000,
    "red": 1000,
    "yellow": 2000,
    "green": 2000,
    "darkBlue": 2000,
    "gold": 2000,
}

# ---------------------------------------------------------------------------
# 租金倍率: 0=空地1x, 1=房屋3x, 2=公寓6x, 3=酒店12x, 4=地标20x
# （规则文档第94-99行）
# ---------------------------------------------------------------------------

RENT_MULTIPLIER: tuple[int, ...] = (1, 3, 6, 12, 20)

# ---------------------------------------------------------------------------
# 空间定义
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Space:
    """棋盘上一个不可变的空间。"""

    position: int
    name: str
    type: str
    price: int | None = None
    base_rent: int | None = None
    group: str | None = None
    icon: str | None = None


SPACES: tuple[Space, ...] = (
    Space(position=0,  name="起 点",      type="go",          group=None,       price=None, base_rent=None, icon="→"),
    Space(position=1,  name="郊区小径",    type="property",    group="brown",    price=600,  base_rent=60),
    Space(position=2,  name="命 运",       type="destiny",     group=None,       price=None, base_rent=None, icon="◆"),
    Space(position=3,  name="田园路",      type="property",    group="brown",    price=600,  base_rent=60),
    Space(position=4,  name="所得税",      type="tax",         group=None,       price=None, base_rent=None, icon="💰"),
    Space(position=5,  name="山谷道",      type="property",    group="lightBlue", price=600,  base_rent=60),
    Space(position=6,  name="林间路",      type="property",    group="lightBlue", price=600,  base_rent=60),
    Space(position=7,  name="机 会",       type="chance",      group=None,       price=None, base_rent=None, icon="?"),
    Space(position=8,  name="湖畔道",      type="property",    group="pink",     price=600,  base_rent=60),
    Space(position=9,  name="春风路",      type="property",    group="pink",     price=600,  base_rent=60),
    Space(position=10, name="监狱/探视",   type="jail",        group=None,       price=None, base_rent=None, icon="⚖"),
    Space(position=11, name="商业一街",    type="property",    group="orange",   price=1200, base_rent=120),
    Space(position=12, name="命 运",       type="destiny",     group=None,       price=None, base_rent=None, icon="◆"),
    Space(position=13, name="商业二街",    type="property",    group="orange",   price=1200, base_rent=120),
    Space(position=14, name="商业三街",    type="property",    group="orange",   price=1200, base_rent=120),
    Space(position=15, name="机 会",       type="chance",      group=None,       price=None, base_rent=None, icon="?"),
    Space(position=16, name="锦绣路",      type="property",    group="red",      price=1200, base_rent=120),
    Space(position=17, name="明珠大道",    type="property",    group="red",      price=1200, base_rent=120),
    Space(position=18, name="命 运",       type="destiny",     group=None,       price=None, base_rent=None, icon="◆"),
    Space(position=19, name="星光道",      type="property",    group="red",      price=1200, base_rent=120),
    Space(position=20, name="免费停车",    type="freeParking", group=None,       price=None, base_rent=None, icon="P"),
    Space(position=21, name="中央一街",    type="property",    group="yellow",   price=2500, base_rent=250),
    Space(position=22, name="机 会",       type="chance",      group=None,       price=None, base_rent=None, icon="?"),
    Space(position=23, name="中央二街",    type="property",    group="yellow",   price=2500, base_rent=250),
    Space(position=24, name="中央广场",    type="property",    group="yellow",   price=2500, base_rent=250),
    Space(position=25, name="命 运",       type="destiny",     group=None,       price=None, base_rent=None, icon="◆"),
    Space(position=26, name="金融大道",    type="property",    group="green",    price=2500, base_rent=250),
    Space(position=27, name="世纪路",      type="property",    group="green",    price=2500, base_rent=250),
    Space(position=28, name="机 会",       type="chance",      group=None,       price=None, base_rent=None, icon="?"),
    Space(position=29, name="国际中心",    type="property",    group="green",    price=2500, base_rent=250),
    Space(position=30, name="前往监狱",    type="goToJail",    group=None,       price=None, base_rent=None, icon="🔒"),
    Space(position=31, name="黄金海岸",    type="property",    group="darkBlue", price=4000, base_rent=400),
    Space(position=32, name="钻石路",      type="property",    group="darkBlue", price=4000, base_rent=400),
    Space(position=33, name="命 运",       type="destiny",     group=None,       price=None, base_rent=None, icon="◆"),
    Space(position=34, name="帝王台",      type="property",    group="gold",     price=4000, base_rent=400),
    Space(position=35, name="机 会",       type="chance",      group=None,       price=None, base_rent=None, icon="?"),
    Space(position=36, name="至尊道",      type="property",    group="gold",     price=4000, base_rent=400),
    Space(position=37, name="命 运",       type="destiny",     group=None,       price=None, base_rent=None, icon="◆"),
    Space(position=38, name="豪宅税",      type="tax",         group=None,       price=None, base_rent=None, icon="💎"),
    Space(position=39, name="命 运",       type="destiny",     group=None,       price=None, base_rent=None, icon="◆"),
)
