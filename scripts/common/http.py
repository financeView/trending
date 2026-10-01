"""akshare 调用封装：限速 + 指数退避重试。"""
import socket
import time

socket.setdefaulttimeout(30)


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


def call_with_retry(fn, limiter=None, attempts=3, backoffs=(5, 20, 60), desc=""):
    last_err = None
    for i in range(attempts):
        if limiter:
            limiter.wait()
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < attempts - 1:
                time.sleep(backoffs[min(i, len(backoffs) - 1)])
    raise RuntimeError("call failed after %d attempts: %s: %s" % (attempts, desc, last_err))
