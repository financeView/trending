"""Baostock session poison detection + sync circuit (no network)."""
from scripts.common.bars import is_baostock_session_poison


def test_poison_detects_utf8_and_vendor_msgs():
    assert is_baostock_session_poison(
        "'utf-8' codec can't decode byte 0x8d in position 111"
    )
    assert is_baostock_session_poison("接收数据异常，请稍后再试。")
    assert is_baostock_session_poison("baostock login: 网络接收错误。")
    assert is_baostock_session_poison(TimeoutError("vendor call exceeded 60s"))
    assert is_baostock_session_poison("call failed after 2 attempts: … exceeded 60s")


def test_poison_ignores_ordinary_query_errors():
    assert not is_baostock_session_poison("baostock query sh.600000: 无效的证券代码")
    assert not is_baostock_session_poison("No data")
    assert not is_baostock_session_poison(KeyError("missing"))


def test_flags_circuit_skips_per_ticker_fallback():
    """Batch login fail → flags_disabled; must not imply manage_session=True storm."""
    from scripts.sync_bars_sample import flags_session_policy

    manage, disabled = flags_session_policy(batch_ok=False, circuit_open=False)
    assert disabled is True
    assert manage is False

    manage, disabled = flags_session_policy(batch_ok=True, circuit_open=True)
    assert disabled is True
    assert manage is False

    manage, disabled = flags_session_policy(batch_ok=True, circuit_open=False)
    assert disabled is False
    assert manage is False  # batch session owns login
