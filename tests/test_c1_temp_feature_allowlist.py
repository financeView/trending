"""C1: temperature + S_temp AST name set ⊆ §4.1 (+ rank/T_raw/params/math)."""
import ast
from pathlib import Path

ALLOW_NAMES = {
    # §4.1 + helpers used by temp_raw / s_temp
    "MA_f",
    "MA_s",
    "slope_f",
    "slope_s",
    "ADX",
    "plus_di",
    "minus_di",
    "sign",
    "sigma_n",
    "sigma_pctile",
    "ret_k",
    "ret_pctile",
    "P",
    "close_qfq",
    "T_raw",
    "rank",
    "RANK",
    "params",
    "clip",
    "max",
    "min",
    "abs",
    "log",
    "isfinite",
    "float",
    "int",
    "str",
    "bool",
    "Optional",
    "Mapping",
    "Any",
    "compute_s_temp",
    "decide_t_raw_from_features",
    "decide_t_raw",
    # common locals
    "feats",
    "feat",
    "t_raw",
    "dir",
    "pos",
    "str_",
    "bullish",
    "bearish",
    "S0",
    "sign_trend",
    "v",
    "k",
    "out",
    "e",
    # temp_raw / s_temp implementation names (no cross-section)
    "MetricsParams",
    "PRED_KEYS",
    "KeyError",
    "TypeError",
    "ValueError",
    "dict",
    "isinstance",
    "all",
    "b",
    "n",
    "names",
    "needed",
    "p",
    "preds",
    "flag",
    "x",
    "s",
    "t",
    "ma_f",
    "ma_s",
    "adx",
    "slope_up",
    "slope_down",
    "slope_flat",
    "stack_bull",
    "stack_bear",
    "di_bull",
    "di_bear",
    "hot_body",
    "warm_body",
    "cold_body",
    "cool_body",
    "boil_boost",
    "freeze_boost",
    "flat_body",
    "compute_predicates",
    "features_computable",
    "hi",
    "lo",
    "r",
    "sigma",
    "ma",
}

FORBIDDEN_SUBSTR = ("RS_raw", "scores_0_100", "local_stock", "local_l2", "peer_rs", "ROC_")


def _load(path: str) -> ast.AST:
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def test_s_temp_and_temp_raw_forbid_cross_section_names():
    for path in ("scripts/metrics/s_temp.py", "scripts/metrics/temp_raw.py"):
        src = Path(path).read_text(encoding="utf-8")
        for bad in FORBIDDEN_SUBSTR:
            assert bad not in src, (path, bad)


def test_temp_path_ast_names_subset_allowlist():
    """AST-walk both temperature modules (Spec C1 scope)."""
    for path in ("scripts/metrics/s_temp.py", "scripts/metrics/temp_raw.py"):
        tree = _load(path)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        noise = {n for n in names if n.startswith("_")}
        leftover = names - ALLOW_NAMES - noise
        assert not leftover, (path, leftover)
