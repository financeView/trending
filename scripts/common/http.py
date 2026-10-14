"""akshare / vendor 调用封装：限速 + 单次硬超时 + 指数退避重试。

超时只跳过本票调用（上层 warn 后继续）；不写 taxonomy quarantine，下一 run 仍会再试。
"""
from __future__ import annotations

import socket
import threading
import time

socket.setdefaulttimeout(30)

# Per-attempt wall clock; akshare/baostock may ignore socket default and block forever.
DEFAULT_CALL_TIMEOUT_SEC = 60.0

# Permanent vendor failures — retrying only burns the Actions clock (tip cold sync).
_NON_RETRYABLE_SNIPPETS = (
    "No value to decode",
    "No data",
)


def _non_retryable(err: BaseException) -> bool:
    if isinstance(err, (TimeoutError, KeyError)):
        return True
    msg = str(err)
    return any(s in msg for s in _NON_RETRYABLE_SNIPPETS)


class RateLimiter:
    def __init__(self, per_second=3.0):
        self.min_interval = 1.0 / per_second
        self._last = 0.0

    def wait(self):
        now = time.time()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.time()


def _call_once(fn, timeout_sec: float):
    """Run ``fn`` with a hard deadline.

    Daemon worker: timed-out I/O may linger, but does not block process exit
    (Actions job teardown). Main continues; no taxonomy quarantine.
    """
    if timeout_sec is None or timeout_sec <= 0:
        return fn()
    box: list = []

    def _runner():
        try:
            box.append(("ok", fn()))
        except BaseException as e:  # noqa: BLE001 — deliver to joiner
            box.append(("err", e))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        raise TimeoutError("vendor call exceeded %.0fs" % timeout_sec)
    if not box:
        raise RuntimeError("vendor call finished without result")
    kind, payload = box[0]
    if kind == "err":
        raise payload
    return payload


def call_with_retry(
    fn,
    limiter=None,
    attempts=3,
    backoffs=(5, 20, 60),
    desc="",
    call_timeout_sec: float = DEFAULT_CALL_TIMEOUT_SEC,
):
    last_err = None
    for i in range(attempts):
        if limiter:
            limiter.wait()
        try:
            return _call_once(fn, call_timeout_sec)
        except TimeoutError as e:
            # Do not retry: another attempt would stack another orphan worker and
            # race shared vendor sessions (e.g. batch BaostockSession).
            last_err = e
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            if _non_retryable(e) or i >= attempts - 1:
                break
            time.sleep(backoffs[min(i, len(backoffs) - 1)])
    raise RuntimeError(
        "call failed after %d attempts: %s: %s" % (attempts, desc, last_err)
    )
