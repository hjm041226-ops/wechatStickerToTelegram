# -*- coding: utf-8 -*-
"""sticker：make_pack_name 边界 / sticker_set_exists / find_available_pack_start。

make_pack_name 为纯函数，无需 mock。
"""

import pytest

from weixin2tg.telegram.sticker import (
    find_available_pack_start,
    make_pack_name,
    sticker_set_exists,
)
import weixin2tg.telegram.client as tg_client


# ---------------- make_pack_name ----------------

def test_basic():
    assert make_pack_name("emo", "my_bot") == "emo_by_my_bot"


def test_pack_number():
    assert make_pack_name("emo", "my_bot", 1) == "emo_by_my_bot"
    assert make_pack_name("emo", "my_bot", 2) == "emo_2_by_my_bot"
    assert make_pack_name("emo", "my_bot", 12) == "emo_12_by_my_bot"


def test_at_sign_and_upper_botname():
    assert make_pack_name("emo", "@My_Bot") == "emo_by_my_bot"


def test_chinese_base_falls_back():
    # 中文被过滤为空 → fallback "stickers"
    assert make_pack_name("表情包", "my_bot").startswith("stickers_by_my_bot")


def test_invalid_chars_replaced():
    assert make_pack_name("we chat!", "my_bot") == "we_chat_by_my_bot"


def test_strips_old_suffix():
    assert make_pack_name("emo_by_my_bot", "my_bot") == "emo_by_my_bot"


def test_digit_prefix_gets_st_prefix():
    assert make_pack_name("123emo", "my_bot") == "st_123emo_by_my_bot"


def test_overlong_base_truncated_to_64():
    result = make_pack_name("a" * 200, "my_bot")
    assert len(result) <= 64
    assert result.endswith("_by_my_bot")


def test_empty_botname_raises():
    with pytest.raises(RuntimeError):
        make_pack_name("emo", "")


def test_invalid_botname_raises():
    with pytest.raises(RuntimeError):
        make_pack_name("emo", "bot name!")


# ---------------- sticker_set_exists（mock 网络） ----------------

def _fake_exists(monkeypatch, payload):
    calls = {}

    def fake_tg_call(token, method, data=None, **kwargs):
        calls["last"] = data
        if payload is None:
            raise tg_client.TgError(
                "connection reset", error_code=None,
                description="connection reset",
            )
        if isinstance(payload, dict):  # 当作 result 直接返回
            return payload
        raise tg_client.TgError(
            payload,
            error_code=400,
            description=payload,
        )

    monkeypatch.setattr(tg_client, "tg_call", fake_tg_call)
    return calls


def test_exists_true(monkeypatch):
    _fake_exists(monkeypatch, {"set": "data"})
    assert sticker_set_exists("t", "emo_by_bot") is True


def test_exists_false_when_not_found(monkeypatch):
    _fake_exists(monkeypatch, "Bad Request: sticker set not found")
    assert sticker_set_exists("t", "emo_by_bot") is False


def test_exists_false_when_stickerset_invalid(monkeypatch):
    # Telegram 实际最常返回的错误：不存在 = STICKERSET_INVALID
    _fake_exists(monkeypatch, "Bad Request: STICKERSET_INVALID")
    assert sticker_set_exists("t", "emo_by_bot") is False


def test_exists_raises_on_unexpected_400(monkeypatch):
    # 其它 400 错误（如参数缺失）不能当作「不存在」吞掉
    _fake_exists(monkeypatch, "Bad Request: wrong parameter")
    with pytest.raises(RuntimeError):
        sticker_set_exists("t", "emo_by_bot")


def test_exists_raises_on_network_error(monkeypatch):
    _fake_exists(monkeypatch, None)
    with pytest.raises(RuntimeError):
        sticker_set_exists("t", "emo_by_bot")


# ---------------- find_available_pack_start ----------------

def test_returns_first_when_all_free(monkeypatch):
    # 全部未占用 → 从 1 开始
    _fake_exists(monkeypatch, "Bad Request: sticker set not found")
    assert find_available_pack_start("t", "emo", "my_bot", chunk_count=3) == 1


def test_skips_occupied_names(monkeypatch):
    # 模拟 1~2 已占用（getStickerSet 成功 = 存在），第 3 个起连续 2 个空闲 → start=3
    taken = {"emo_by_my_bot", "emo_2_by_my_bot"}

    def fake_tg_call(token, method, data=None, **kwargs):
        name = (data or {}).get("name", "")
        if name in taken:
            return {"set": {"name": name}}  # 已存在 → exists=True
        raise tg_client.TgError(
            "Bad Request: sticker set not found",
            error_code=400,
            description="Bad Request: sticker set not found",
        )

    monkeypatch.setattr(tg_client, "tg_call", fake_tg_call)
    assert find_available_pack_start("t", "emo", "my_bot", chunk_count=2) == 3


def test_exhausts_attempts(monkeypatch):
    def fake_tg_call(token, method, data=None, **kwargs):
        raise tg_client.TgError(
            "Bad Request: sticker set not found",
            error_code=400,
            description="Bad Request: sticker set not found",
        )

    # 全部空闲其实会立即返回 1 —— 制造“永远占用”才能测到耗尽：
    # 把逻辑反转：模拟 getStickerSet 永远返回成功
    def fake_always_exists(token, method, data=None, **kwargs):
        if method == "getStickerSet":
            return {"set": "exists"}
        return True

    monkeypatch.setattr(tg_client, "tg_call", fake_always_exists)
    with pytest.raises(RuntimeError, match="无法找到可用"):
        find_available_pack_start("t", "emo", "my_bot", chunk_count=1, max_attempts=3)
