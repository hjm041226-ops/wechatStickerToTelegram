# -*- coding: utf-8 -*-
"""Sticker Pack 名称规划：合法性、占用检查、连续可用区间查找。

所有函数只依赖 client.tg_call，网络层全部可被 mock。
"""

import re

import weixin2tg.telegram.client as client
from weixin2tg.logging_setup import get_logger

logger = get_logger(__name__)


def make_pack_name(base_name, bot_uname, pack_number=1):
    """生成合法 Telegram Sticker Set short name。

    规则（Telegram Bot API）：
    1. 必须以字母开头
    2. 只能包含 a-z、0-9、_
    3. 必须以 _by_<bot_username> 结尾
    4. 总长不超过 64 字符

    示例：
        base="emo" + bot="my_bot" + pack=1 → emo_by_my_bot
        base="emo" + bot="my_bot" + pack=2 → emo_2_by_my_bot
    """
    # Bot username 清洗与校验
    bot_uname = (bot_uname or "").strip().lstrip("@").lower()
    if not bot_uname:
        raise RuntimeError("Bot username 为空，无法创建 Sticker Pack")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", bot_uname):
        raise RuntimeError(f"Bot username 无效：{bot_uname!r}")

    # base 清洗：小写 → 去掉旧 _by_xxx 后缀 → 非法字符转 _ → 合并连续 _ → 去首尾 _
    base = (base_name or "").strip().lower()
    base = re.sub(r"_by_[a-z0-9_]+$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"[^a-z0-9_]", "_", base)
    base = re.sub(r"_+", "_", base)
    base = base.strip("_")

    if not base:
        base = "stickers"
    if not re.match(r"^[a-z]", base):
        base = "st_" + base

    # 分包编号：第 2 包起追加 _N
    if pack_number > 1:
        base = f"{base}_{int(pack_number)}"

    # 截断以容纳 _by_<bot> 后缀
    suffix = f"_by_{bot_uname}"
    max_base_length = 64 - len(suffix)
    if max_base_length < 1:
        raise RuntimeError("Bot username 太长，无法生成合法 Sticker Pack 名称")

    base = base[:max_base_length].rstrip("_")
    if not base:
        base = "s"
    if not re.match(r"^[a-z]", base):
        base = "s" + base
        base = base[:max_base_length]

    result = base + suffix

    # 最终验证（防御性，正常流程不应触发）
    if len(result) > 64:
        raise RuntimeError(f"Sticker Pack 名称超过 64 字符：{result}")
    if not re.fullmatch(r"[a-z][a-z0-9_]*_by_[a-z][a-z0-9_]*", result):
        raise RuntimeError(f"生成的 Sticker Pack 名称不合法：{result}")

    return result


def sticker_set_exists(token, set_name):
    """检查 Sticker Pack 是否存在。

    返回 True = 已存在；False = 明确不存在；其余异常原样抛出（网络错误等）。

    Telegram 对「查询一个不存在的贴纸集」实际返回两种 400 描述：
    - Bad Request: STICKERSET_INVALID（贴纸集无效/不存在，最常见）
    - Bad Request: sticker set not found（部分场景）
    由于 make_pack_name 已保证名字格式合法，这两种情况都可安全视为「该名字可用」。
    """
    try:
        client.tg_call(token, "getStickerSet", data={"name": set_name}, timeout=30)
        return True
    except client.TgError as exc:
        if exc.error_code == 400:
            description = exc.description.lower()
            if "not found" in description or "stickerset_invalid" in description:
                return False
        raise RuntimeError(f"检查 Sticker Pack 失败：{exc}") from exc


def find_available_pack_start(token, base_name, bot_uname, chunk_count, max_attempts=100):
    """查找一组「连续 N 个」都未被占用的起始包号。

    例如需要 3 个包、base="emo"、bot="my_bot"：
        找到 start=1 → emo_by_my_bot / emo_2_by_my_bot / emo_3_by_my_bot
    若 1、2 已被占用 → start=3 → emo_3 / emo_4 / emo_5
    """
    for start_number in range(1, max_attempts + 1):
        available = True
        for offset in range(chunk_count):
            pack_number = start_number + offset
            set_name = make_pack_name(base_name, bot_uname, pack_number)
            logger.info("[Telegram] 检查 Sticker Pack: %s", set_name)
            if sticker_set_exists(token, set_name):
                logger.info("[Telegram] 已存在: %s", set_name)
                available = False
                break
            logger.info("[Telegram] 可用: %s", set_name)
        if available:
            return start_number

    raise RuntimeError(f"无法找到可用的 Telegram Sticker Pack 名称，已尝试 {max_attempts} 个起始编号")
