# -*- coding: utf-8 -*-
"""扫描与格式识别。

- sniff_format：按文件头识别真实格式（扩展名写错也能用）
- scan_folder：扫描磁盘文件夹
- prepare_items：过滤非法文件并生成预览图（写入 PREVIEW_DIR）
"""

import os
import shutil

from PIL import Image

from weixin2tg import config
from weixin2tg.logging_setup import get_logger

logger = get_logger(__name__)

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# 单文件上限 20MB（Telegram Bot API 限制）
MAX_FILE_SIZE = 20 * 1024 * 1024

# 常见的会被误选的元数据文件扩展名（可选扩展用）
_IGNORE_NAMES = {"thumbs.db", ".ds_store"}


def sniff_format(path):
    """按文件内容判断类型。

    返回 "gif"（GIF / 动态 WebP）/ "static"（PNG/JPG/BMP/静态 WebP）/ None。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None

    # GIF
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"

    # WEBP（RIFF....WEBP），动态与否交给 Pillow
    if head[:8] == b"RIFF" and head[8:12] == b"WEBP":
        try:
            with Image.open(path) as im:
                return "gif" if getattr(im, "is_animated", False) else "static"
        except Exception:
            return None

    # JPG / BMP / PNG
    if head[:2] == b"\xff\xd8":
        return "static"
    if head[:2] == b"BM":
        return "static"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "static"

    return None


def _iter_folder(folder):
    """遍历文件夹顶层，产出 {name, path}（按文件名排序，稳定输出）。"""
    try:
        names = sorted(os.listdir(folder))
    except OSError as exc:
        raise RuntimeError(f"无法读取文件夹：{exc}") from exc

    for name in names:
        if name.lower() in _IGNORE_NAMES:
            continue
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            yield name, path


def scan_folder(folder):
    """按磁盘路径扫描文件夹，返回 items 原始列表（未做格式过滤）。"""
    folder = str(folder or "").strip()
    if not folder:
        raise RuntimeError("缺少文件夹路径")
    if not os.path.isdir(folder):
        raise RuntimeError(f"文件夹不存在：{folder}")

    items = []
    for name, path in _iter_folder(folder):
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXTS:
            continue
        items.append({"id": _gen_id(), "name": name, "path": path})
    return items


def _gen_id(length=12):
    """生成随机 id（延迟 import uuid，避免无关开销）。"""
    import uuid

    return uuid.uuid4().hex[:length]


def prepare_items(items, on_step=None):
    """过滤不可用文件，生成预览图，返回带 kind/size/preview 的 items。

    副作用：清空 PREVIEW_DIR 并重建（单用户本地工具，可接受）。

    on_step(phase, index, total, name)：可选逐文件进度回调。phase 为
    "识别"（读文件头判断类型）或 "预览"（复制生成预览图），供后台
    扫描任务展示真实进度；None 时保持纯同步行为（/api/scan 用）。
    """
    result = []
    total = len(items)
    for index, item in enumerate(items, 1):
        name = item.get("name", "")
        if on_step:
            on_step("识别", index, total, name)
        path = item.get("path")
        if not path or not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        kind = sniff_format(path)
        if kind is None:
            continue
        if size > MAX_FILE_SIZE:
            continue

        item["kind"] = kind
        item["size"] = size
        result.append(item)

    # 重建预览目录
    shutil.rmtree(config.PREVIEW_DIR, ignore_errors=True)
    os.makedirs(config.PREVIEW_DIR, exist_ok=True)

    preview_total = len(result)
    for index, item in enumerate(result, 1):
        if on_step:
            on_step("预览", index, preview_total, item.get("name", ""))
        if item["kind"] == "gif":
            ext = ".gif"
        else:
            ext = os.path.splitext(item["name"])[1].lower() or ".png"
        out = os.path.join(config.PREVIEW_DIR, item["id"] + ext)
        try:
            shutil.copyfile(item["path"], out)
            item["preview"] = f"/preview/{item['id']}{ext}"
        except Exception:
            continue

    return result
