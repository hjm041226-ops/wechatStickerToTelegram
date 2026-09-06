# -*- coding: utf-8 -*-
"""贴纸集上传编排：从文件列表到 Telegram 贴纸包。

原 tg_upload_set（约 380 行）按职责拆成三段：
1. _plan_pack_names —— 分包 + 命名规划（只读检查，不做任何写入）
2. _create_sticker_set —— 用 createNewStickerSet 创建包（≤50 张/次批量）
3. 追加剩余贴纸 —— 并发 addStickerToSet，实时汇报进度

对外入口 upload_set() 只接收纯数据 + progress 回调，不感知 Job 结构。
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil

import weixin2tg.telegram.client as client
from weixin2tg.logging_setup import get_logger
from weixin2tg.telegram.sticker import (
    find_available_pack_start,
    make_pack_name,
    sticker_set_exists,
)

logger = get_logger(__name__)

# Telegram 单包贴纸上限
TG_MAX_PER_SET = 120
# createNewStickerSet 单次最多携带的贴纸数
TG_CREATE_BATCH = 50

# addStickerToSet 并发线程数。
# 直连 api.telegram.org 时过高的并发 TLS 连接容易被掐断（SSLEOFError），
# 之前因 SSL 错误较多降到 2；Session 复用 + SSL 退避缩短后，3 通常稳定。
# 仍出现大量 SSL 断连时可用环境变量 WX2TG_UPLOAD_WORKERS=1 进一步降级。
_UPLOAD_WORKERS = int(os.environ.get("WX2TG_UPLOAD_WORKERS", "3"))

# 写入类接口（createNewStickerSet / addStickerToSet）的最小请求间隔（秒）。
# Telegram 对贴纸写入有分钟级配额：3 个 worker 若同时发请求会集体撞 429，
# 每次罚站 retry_after 可达 50s+；主动错峰匀速（约 0.8 请求/s）通常比
# 被动吃惩罚快得多。可用环境变量 WX2TG_MIN_UPLOAD_INTERVAL 覆盖。
_UPLOAD_MIN_INTERVAL = float(os.environ.get("WX2TG_MIN_UPLOAD_INTERVAL", "1.2"))

# 上传场景的重试次数（网络不稳时比默认更耐心；总尝试 = retries + 1）
_UPLOAD_RETRIES = 5

# 默认 emoji
EMOJI = ["😀"]


# ============================================================
# 创建 Sticker Set（multipart 批量）
# ============================================================

def _create_sticker_set(token, owner_id, name, title, kind, batch_paths):
    """用 createNewStickerSet 创建贴纸包，一次最多 TG_CREATE_BATCH 张。

    关键点：Telegram 要求 multipart 里用 attach://fN 引用文件，
    且 sticker 的 format 必须是 "static" / "video" / "animated"。
    文件句柄在请求结束后统一关闭。
    """
    stickers = []
    opened = {}

    try:
        for index, path in enumerate(batch_paths):
            key = f"f{index}"
            opened[key] = open(path, "rb")
            stickers.append(
                {
                    "sticker": f"attach://{key}",
                    "emoji_list": EMOJI,
                    "format": kind,  # "static"（PNG/WebP）或 "video"（WEBM）
                }
            )

        data = {
            "user_id": str(owner_id),
            "name": name,
            "title": title,
            "stickers": json.dumps(stickers, ensure_ascii=False),
        }

        logger.info("createNewStickerSet: name=%s title=%s count=%d", name, title, len(batch_paths))
        client.tg_call(
            token, "createNewStickerSet",
            data=data, files=opened,
            timeout=180, retries=_UPLOAD_RETRIES,
            min_interval=_UPLOAD_MIN_INTERVAL,
        )
    finally:
        for handle in opened.values():
            try:
                handle.close()
            except Exception:
                pass


# ============================================================
# 追加单个贴纸（并发 worker 用）
# ============================================================

def _add_one_sticker(token, owner_id, set_name, kind, path):
    """向已创建的贴纸包追加一张贴纸。"""
    data = {
        "user_id": str(owner_id),
        "name": set_name,
        "sticker": json.dumps(
            {
                "sticker": "attach://f",
                "emoji_list": EMOJI,
                "format": kind,
            },
            ensure_ascii=False,
        ),
    }
    with open(path, "rb") as handle:
        client.tg_call(
            token, "addStickerToSet",
            data=data, files={"f": handle},
            timeout=180, retries=_UPLOAD_RETRIES,
            min_interval=_UPLOAD_MIN_INTERVAL,
        )


# ============================================================
# 分包 + 命名规划（只读 Telegram，不写入）
# ============================================================

def _plan_pack_names(token, bot_uname, base_name, title, files_list, chunk_nums):
    """规划「哪些包要传、各自叫什么名字、装哪些文件」。

    返回 list[dict]：
        {chunk_num, number, name, title, files}
    其中 number 是最终包序号（用于名字与标题），
    files 是这一包要上传的本地文件路径列表。
    """
    total = len(files_list)
    total_chunks = ceil(total / TG_MAX_PER_SET)

    # 用户指定要传哪些分包（从 1 开始）
    if chunk_nums is not None:
        selected = sorted(
            int(x) for x in chunk_nums if 1 <= int(x) <= total_chunks
        )
    else:
        selected = list(range(1, total_chunks + 1))

    if not selected:
        return []

    # 是否整组上传（决定用「连续区间查找」还是「逐包找空闲名」）
    full_upload = chunk_nums is None or len(selected) == total_chunks

    # number_for_chunk：把用户看到的「第 N 包」映射到实际包序号
    if full_upload:
        start_number = find_available_pack_start(
            token=token,
            base_name=base_name,
            bot_uname=bot_uname,
            chunk_count=total_chunks,
        )
        # 第 1 包 → start，第 2 包 → start+1，……
        number_for_chunk = {
            chunk_num: start_number + (chunk_num - 1)
            for chunk_num in selected
        }
    else:
        # 部分上传：第 N 包优先用 N 号，被占用就顺延。
        # 把每个 chunk 的 [chunk_num .. chunk_num+PROBE) 候选一次性并发预查，
        # 比原来的「N 个 chunk × 串行顺延」快 N 倍。
        _PROBE_PER_CHUNK = 30
        chunk_candidates = {}  # chunk_num -> [(number, name), ...]
        for cn in selected:
            chunk_candidates[cn] = []
            for offset in range(_PROBE_PER_CHUNK):
                n = cn + offset
                if n > 100:
                    break
                chunk_candidates[cn].append((n, make_pack_name(base_name, bot_uname, n)))

        # 收集所有要查的包名（去重：不同 chunk 的候选可能产生同名 name）
        all_names = []
        seen = set()
        for lst in chunk_candidates.values():
            for _n, name in lst:
                if name not in seen:
                    seen.add(name)
                    all_names.append(name)

        # 并发查所有唯一包名（8 worker，远超选中分包的常规数量）
        with ThreadPoolExecutor(max_workers=8) as pool:
            name_exists = dict(pool.map(
                lambda name: (name, sticker_set_exists(token, name)),
                all_names,
            ))

        # 给每个 chunk 分配第一个可用的 number（保持与原版「按编号小优先」语义一致）
        number_for_chunk = {}
        for cn in selected:
            for n, name in chunk_candidates[cn]:
                if not name_exists.get(name, False):
                    number_for_chunk[cn] = n
                    break
            else:
                raise RuntimeError(
                    f"无法为分包 {cn} 找到可用的 Sticker Pack 名称（已探测 {_PROBE_PER_CHUNK} 个）"
                )

    plan = []
    for chunk_num in selected:
        number = number_for_chunk[chunk_num]
        name = make_pack_name(base_name, bot_uname, number)

        # 标题：第一个包用原名，之后追加序号
        if number == 1:
            pack_title = title
        else:
            pack_title = f"{title} {number}"
        pack_title = pack_title[:64]

        start = (chunk_num - 1) * TG_MAX_PER_SET
        chunk_files = files_list[start:start + TG_MAX_PER_SET]
        if not chunk_files:
            continue

        plan.append(
            {
                "chunk_num": chunk_num,
                "number": number,
                "name": name,
                "title": pack_title,
                "files": chunk_files,
            }
        )

    return plan


# ============================================================
# 编排入口
# ============================================================

def upload_set(
    token,
    owner_id,
    base_name,
    title,
    kind,
    files_list,
    bot_uname,
    chunk_nums=None,
    label="",
    progress=None,
):
    """上传一个类型（静态或动图）的全部贴纸，自动拆包 + 自动找可用名。

    参数：
    - files_list：按顺序排列的本地文件路径列表（可能是全量）
    - chunk_nums：要上传的分包序号（1-based）；None 表示全部
    - label：进度消息前缀（如 "静态" / "动态"）
    - progress：回调 progress(percent: int, message: str)，
      percent 是「本次实际计划上传文件」（勾选分包内文件）的完成占比（0-99），
      由上层决定如何展示

    返回：实际创建的贴纸包名列表 created。
    """
    created = []

    file_count = len(files_list)
    if file_count == 0:
        return created

    bot_uname = (bot_uname or "").strip().lstrip("@").lower()
    if not bot_uname:
        raise RuntimeError("Telegram Bot username 为空")

    plan = _plan_pack_names(token, bot_uname, base_name, title, files_list, chunk_nums)
    if not plan:
        return created

    # 进度分母 = 本次计划上传（勾选分包）的文件总数，而不是全量文件。
    # 否则只勾选 1 个分包时 total 会错误地显示全部文件数。
    planned_total = sum(len(entry["files"]) for entry in plan)
    if planned_total <= 0:
        return created

    processed = 0  # 已处理（成功进入某个包）的文件数，用于算进度

    def report(extra=0, message=""):
        percent = min(99, int((processed + extra) / planned_total * 100))
        if progress:
            progress(percent, message or "")

    for entry in plan:
        name = entry["name"]
        chunk = entry["files"]

        logger.info("准备创建 Sticker Pack: name=%s title=%s kind=%s count=%d",
                    name, entry["title"], kind, len(chunk))

        report(0, f"{label}: 正在检查/创建包 {name}…")

        # ---------------- 创建包（首批 ≤50 张） ----------------
        first_batch = chunk[:TG_CREATE_BATCH]
        if not first_batch:
            continue

        try:
            _create_sticker_set(
                token, owner_id, name, entry["title"], kind, first_batch,
            )
        except client.TgError as exc:
            # 检查与创建之间被抢先占名的竞态 → 友好提示重试
            if "already occupied" in exc.description.lower():
                raise RuntimeError(
                    f"{label} Sticker Pack 名称刚刚被占用：{name}\n"
                    "请重新上传，程序会自动选择下一个名称。"
                ) from exc
            raise

        created.append(name)
        processed += len(first_batch)
        report(0, f"{label}: 已创建包 {name}")

        # ---------------- 剩余贴纸：并发追加 ----------------
        rest = chunk[TG_CREATE_BATCH:]
        if not rest:
            continue

        done = [0]
        errors = []
        pool_size = min(_UPLOAD_WORKERS, len(rest))

        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            futures = {
                pool.submit(_add_one_sticker, token, owner_id, name, kind, path): path
                for path in rest
            }
            for future in as_completed(futures):
                path = futures[future]
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001 —— 聚合错误统一抛出
                    logger.warning("addStickerToSet 失败: %s -> %s", os.path.basename(path), exc)
                    errors.append(f"{os.path.basename(path)}: {exc}")
                done[0] += 1
                report(done[0], f"{label}: 上传中 {processed + done[0]}/{planned_total}（并发 {pool_size}）")

        processed += len(rest)

        if errors:
            message = "；".join(errors[:3])
            # 若失败集中在网络/SSL，附加可操作建议
            if any(
                ("网络请求失败" in e or "SSLError" in e or "ConnectionError" in e)
                for e in errors
            ):
                message += (
                    "\n提示：连续 SSL/网络失败通常是直连 Telegram 被干扰或并发过高。"
                    "可设置环境变量 WX2TG_UPLOAD_WORKERS=1 降低并发后重试；"
                    "或稍等片刻再次上传（已成功创建的同名包会自动顺延编号，不会重复）。"
                )
            raise RuntimeError(message)

    return created
