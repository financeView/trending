from scripts.common.taxonomy_meta import (
    RADAR_TITLE,
    l1_issue_title,
    load_l1_buckets,
)


def test_load_fourteen_canonical_l1_buckets():
    buckets = load_l1_buckets()
    assert len(buckets) == 14
    ids = [b.l1_id for b in buckets]
    assert ids[0] == "l1_health"
    assert ids[-1] == "l1_diversified"
    assert len(set(ids)) == 14
    titles = [l1_issue_title(b) for b in buckets]
    assert len(set(titles)) == 14
    assert titles[ids.index("l1_finance")] == "[L1] 金融 (l1_finance)"
    assert RADAR_TITLE == "[Radar] A股战场"
