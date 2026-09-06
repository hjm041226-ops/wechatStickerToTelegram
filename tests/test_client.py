# -*- coding: utf-8 -*-
"""telegram/client 层单测（节流闸等纯逻辑，不触网）。"""

import pytest

from weixin2tg.telegram import client


class _FakeTime:
    """可控的假 time：monotonic 返回内部时钟，sleep 记录并推进时钟。"""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_gate_wait_serializes_min_interval(monkeypatch):
    """距上次放行不足间隔时应补足睡眠；足够久则直接放行。"""
    fake = _FakeTime()
    monkeypatch.setattr(client, "time", fake)
    client._gate_last = 0.0  # 很久没请求

    # 第一次：距上次足够久，不睡
    client._gate_wait(1.2)
    assert fake.sleeps == []

    # 第二次：距上次仅一瞬间，必须睡满 ~1.2s 补足间隔
    client._gate_wait(1.2)
    assert len(fake.sleeps) == 1
    assert fake.sleeps[0] == pytest.approx(1.2, abs=0.05)

    # 第三次：时钟已被 sleep 推进，仍要再次补足（多 worker 错峰持续成立）
    client._gate_wait(1.2)
    assert fake.sleeps[1] == pytest.approx(1.2, abs=0.05)


def test_gate_wait_zero_interval_noop(monkeypatch):
    """min_interval<=0（默认查询类调用）完全不过闸、不睡眠。"""
    fake = _FakeTime()
    monkeypatch.setattr(client, "time", fake)
    client._gate_last = fake.monotonic()  # 模拟刚发过请求

    client._gate_wait(0.0)
    client._gate_wait(-1)
    assert fake.sleeps == []
