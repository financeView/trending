"""Shared named-fixture runner for §6.4 / §8.9 CI suites."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from scripts.metrics.params import load_params
from scripts.metrics.pipeline import replay_days

ROOT = Path(__file__).resolve().parents[1]
PARAMS = load_params(ROOT / "config" / "metrics" / "a_share_daily.yaml")


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def fixture_ids(directory: Path) -> set[str]:
    return {p.stem for p in directory.glob("*.json")}


def assert_required_ids(directory: Path, required: Sequence[str]) -> None:
    found = fixture_ids(directory)
    missing = [i for i in required if i not in found]
    assert not missing, f"required fixture IDs missing in {directory}: {missing}"


def _values_equal(expect: Any, actual: Any) -> bool:
    if expect is None:
        return actual is None
    if isinstance(expect, bool) or isinstance(actual, bool):
        return expect is actual if isinstance(actual, bool) else expect == actual
    if isinstance(expect, (int, float)) and isinstance(actual, (int, float)):
        return actual == pytest.approx(expect)
    return expect == actual


def _match_day(expect: Mapping[str, Any], snap: Mapping[str, Any], *, loc: str) -> None:
    for key, want in expect.items():
        if key == "i":
            continue
        if key == "finite" and want:
            for num_key in (
                "stage_score",
                "stage_score_raw",
                "stage_score_peak",
                "g_raw",
                "g_raw_eff",
                "g_clamped",
            ):
                val = snap.get(num_key)
                if val is not None:
                    assert math.isfinite(val), f"{loc}: {num_key} not finite ({val})"
            continue
        assert key in snap, f"{loc}: snapshot missing key {key!r}"
        got = snap[key]
        assert _values_equal(want, got), f"{loc}: {key} expected {want!r} got {got!r}"


def run_named_fixture(path: Path) -> list[dict[str, Any]]:
    spec = load_fixture(path)
    fid = spec.get("id", path.stem)
    assert fid == path.stem, f"{path.name}: id {fid!r} != filename stem"
    snaps = replay_days(PARAMS, spec["days"], init=spec.get("init"))
    expect = spec.get("expect") or {}
    day_exps = expect.get("days") or []
    for exp in day_exps:
        i = int(exp["i"])
        assert 0 <= i < len(snaps), f"{fid}: expect i={i} out of range ({len(snaps)} days)"
        _match_day(exp, snaps[i], loc=f"{fid}[{i}]")
    all_exp = expect.get("all")
    if all_exp:
        for i, snap in enumerate(snaps):
            _match_day(all_exp, snap, loc=f"{fid}[all:{i}]")
    never_terms = expect.get("never_terms") or []
    for i, snap in enumerate(snaps):
        term = snap.get("solar_term")
        assert term not in never_terms, f"{fid}[{i}]: forbidden solar_term {term}"
    return snaps
