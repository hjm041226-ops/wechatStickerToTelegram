# -*- coding: utf-8 -*-
"""贴纸转换器：静态图 → PNG/WebP，动图 → WEBM。

- build_static_sticker：缩放至 512px 内；超过 512KB 自动转 WebP
- build_animated_sticker：调用 ffmpeg 转 WEBM（VP9，≤3s，512x512）
- find_ffmpeg：缓存式查找内嵌 / 系统 ffmpeg
"""

import os
import shutil
import subprocess

from PIL import Image

from weixin2tg import config
from weixin2tg.logging_setup import get_logger

logger = get_logger(__name__)

# Telegram 静态贴纸建议边长
TG_STICKER_SIZE = 512
# 静态贴纸文件大小阈值（超过转 WebP 压缩）
TG_STATIC_MAX_BYTES = 512 * 1024

# ffmpeg 候选路径（bundled → 系统 PATH）
_BUNDLED_FFMPEG = [
    os.path.join(config.BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe"),
    os.path.join(config.BASE_DIR, "ffmpeg.exe"),
    r"C:\ffmpeg\bin\ffmpeg.exe",
]

_ffmpeg_cache = {"path": None, "tried": False}


def find_ffmpeg(configured=None):
    """查找 ffmpeg 可执行文件（结果缓存）。

    configured 传入时只校验该路径是否真实存在。
    """
    if configured:
        return configured if os.path.isfile(configured) else None

    if _ffmpeg_cache["tried"]:
        return _ffmpeg_cache["path"]

    found = (
        next((p for p in _BUNDLED_FFMPEG if os.path.isfile(p)), None)
        or shutil.which("ffmpeg")
    )
    _ffmpeg_cache["tried"] = True
    _ffmpeg_cache["path"] = found
    return found


def build_static_sticker(src, out_base):
    """静态图 → PNG（512px）；超过 512KB 自动转 WebP。

    返回最终文件名（xxx.png 或 xxx.webp），文件写入 out_base 同目录。
    """
    out_png = out_base + ".png"

    with Image.open(src) as im:
        im = im.convert("RGBA")
        w, h = im.size
        if w <= 0 or h <= 0:
            raise RuntimeError("图片尺寸无效")

        scale = TG_STICKER_SIZE / max(w, h)
        if scale != 1.0:
            new_w = max(1, round(w * scale))
            new_h = max(1, round(h * scale))
            im = im.resize((new_w, new_h), Image.LANCZOS)

        im.save(out_png, "PNG", optimize=True)

        # Telegram 上传上限约 512KB，超出转 WebP（同尺寸透明压缩）
        if os.path.getsize(out_png) > TG_STATIC_MAX_BYTES:
            out_webp = out_base + ".webp"
            im.save(out_webp, "WEBP", quality=90, method=6)
            try:
                os.remove(out_png)
            except OSError:
                pass
            return os.path.basename(out_webp)

    return os.path.basename(out_png)


def build_animated_sticker(src, out_base, ffmpeg):
    """GIF / 动态 WebP → WEBM（VP9，≤3s，512x512 透明底）。"""
    out_webm = out_base + ".webm"

    cmd = [
        ffmpeg,
        "-y",
        "-i", src,
        "-t", "3.0",  # 最长 3 秒
        "-vf",
        (
            "fps=30,"
            "scale=512:512:force_original_aspect_ratio=decrease,"
            "pad=512:512:-1:-1:color=0x00000000,"
            "format=yuva420p"
        ),
        "-c:v", "libvpx-vp9",
        "-b:v", "256k",
        "-crf", "30",
        "-an",
        "-auto-alt-ref", "0",
        out_webm,
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=creationflags,
        timeout=120,
    )

    if result.returncode != 0:
        error = (result.stderr or result.stdout or "未知 FFmpeg 错误")
        raise RuntimeError("ffmpeg 转码失败: " + error[-800:])

    if not os.path.isfile(out_webm):
        raise RuntimeError("FFmpeg 转码完成，但没有生成 WEBM 文件")

    return os.path.basename(out_webm)
