import csv
from pathlib import Path

from scripts.metrics.temp_raw import decide_t_raw


def test_temp_raw_gold():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "temp_raw_gold.csv"
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 5
    for row in rows:
        got = decide_t_raw(row)
        assert got == row["expect_T_raw"], (row["id"], got, row["expect_T_raw"])
