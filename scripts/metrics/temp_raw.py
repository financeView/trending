"""MVP T_raw 决策（对齐 fixtures/temp_raw_gold.csv 布尔列）。

完整 metrics §5.1/§5.2 谓词（MA/ADX/σ%ile）在后续任务接入；
本模块先保证金标路径与七档全序可测。
"""
from __future__ import annotations

from typing import Mapping


RANK = ["冻", "寒", "凉", "平", "温", "热", "沸"]


def decide_t_raw(feats: Mapping[str, int | bool]) -> str:
    """feats: 0/1 或 bool，键同 gold CSV。"""

    def b(k: str) -> bool:
        return bool(int(feats.get(k, 0)))

    # 全序唯一命中（与 gold 行一致的简化树）
    if b("ret_extreme_down") and b("vol_high") and not b("above_ma20"):
        return "冻"
    if b("adx_ge_hot") and not b("above_ma20") and not b("above_ma60") and not b("ret_extreme_down"):
        return "寒"
    if (not b("above_ma20")) and b("adx_ge_warm") and not b("adx_ge_hot"):
        return "凉"
    if b("adx_lt_flat") and b("above_ma20") and not b("above_ma60"):
        return "平"
    if b("above_ma20") and b("above_ma60") and b("ma20_slope_up") and not b("ma60_slope_up"):
        return "温"
    if (
        b("above_ma20")
        and b("above_ma60")
        and b("ma20_slope_up")
        and b("ma60_slope_up")
        and b("adx_ge_hot")
        and b("vol_high")
        and b("ret_extreme_up")
    ):
        return "沸"
    if (
        b("above_ma20")
        and b("above_ma60")
        and b("ma20_slope_up")
        and b("ma60_slope_up")
        and b("adx_ge_hot")
    ):
        return "热"
    return "平"


def rank(t: str) -> int:
    return RANK.index(t)
